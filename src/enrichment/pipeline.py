"""Document enrichment pipeline — IOC extraction, geocoding, full LLM enrichment."""
import json
import re
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from framework.commons.logger import logger

from src.config import Config

# ── IOC regex patterns ─────────────────────────────────────────────────────────

_RE_IP       = re.compile(r'\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b')
_RE_URL      = re.compile(r'https?://[^\s<>"\'{}|\\^`\[\]]+', re.IGNORECASE)
_RE_EMAIL    = re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,7}\b')
_RE_MD5      = re.compile(r'\b[a-fA-F0-9]{32}\b')
_RE_SHA1     = re.compile(r'\b[a-fA-F0-9]{40}\b')
_RE_SHA256   = re.compile(r'\b[a-fA-F0-9]{64}\b')
_RE_CVE      = re.compile(r'\bCVE-\d{4}-\d{4,7}\b', re.IGNORECASE)
_RE_PATH     = re.compile(r'(?:/(?:etc|var|home|tmp|usr|bin|sbin|opt|root|proc|sys|data|log)[/\w.\-]*|[A-Za-z]:\\[^\s<>"\']+)')
_RE_HASHTAG  = re.compile(r'#[\w\u0400-\u04FF\u0600-\u06FF]{2,}')
_RE_DOMAIN   = re.compile(
    r'\b(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+(?:com|net|org|io|gov|mil|edu|info|biz|onion'
    r'|ru|cn|de|uk|fr|nl|xyz|app|cloud|online|site|tech|int|us|ca|au|jp|kr|br|in|pl|se|no|dk|fi)\b',
    re.IGNORECASE,
)


def extract_iocs(text: str) -> dict:
    """Regex-based Indicator of Compromise extraction — no LLM required."""
    urls  = list(set(_RE_URL.findall(text)))
    clean = _RE_URL.sub(' ', text)
    hashes = list(set(_RE_MD5.findall(text) + _RE_SHA1.findall(text) + _RE_SHA256.findall(text)))
    return {
        "ips":        list(set(_RE_IP.findall(text))),
        "domains":    [d for d in set(_RE_DOMAIN.findall(clean)) if len(d) > 4],
        "urls":       urls,
        "emails":     list(set(_RE_EMAIL.findall(text))),
        "hashes":     hashes,
        "cves":       list(set(_RE_CVE.findall(text))),
        "file_paths": list(set(_RE_PATH.findall(text))),
        "hashtags":   list(set(_RE_HASHTAG.findall(text))),
    }


def geocode_location(name: str) -> dict | None:
    """Geocode a place name via Nominatim (OpenStreetMap). Returns None on failure."""
    try:
        params = urllib.parse.urlencode({"q": name, "format": "json", "limit": 1})
        req = urllib.request.Request(
            f"https://nominatim.openstreetmap.org/search?{params}",
            headers={"User-Agent": "QSINT-RAG-Intelligence-Platform/1.0"},
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            results = json.loads(resp.read().decode())
        if results:
            return {
                "name":         name,
                "lat":          float(results[0]["lat"]),
                "lon":          float(results[0]["lon"]),
                "display_name": results[0].get("display_name", name),
            }
    except Exception as e:
        logger.warning(f"[geocode] '{name}': {e}")
    return None


def run_enrichment_background(datasource: str, doc_id: str, text: str) -> None:
    """Background worker: full document enrichment via LLM + IOC regex + geocoding."""
    from src.enrichment.models import DocumentEnrichment
    from src.core.db import get_db
    from src.llm.client import get_llm
    from src.llm.prompts import PromptBuilder
    from src.insights.engine import InsightsEngine

    try:
        with get_db() as db:
            row = db.query(DocumentEnrichment).filter_by(doc_id=doc_id, datasource=datasource).first()
            if row:
                row.status = "processing"
                row.started_at = datetime.now(timezone.utc)
                db.commit()
                logger.info(f"[enrich] Document {doc_id} status → processing")
    except Exception as e:
        logger.error(f"[enrich] DB pre-update failed: {e}")
        return

    try:
        builder = PromptBuilder()
        llm = get_llm()

        messages, system = builder.build_enrichment_messages(text[:3000])
        raw = llm.complete_json(messages, system)
        payload = InsightsEngine._parse_json(raw)

        if payload is None:
            logger.warning(f"[enrich] doc_id={doc_id} JSON parse fail, retrying with temperature=0.3...")
            raw = llm.complete_json(messages, system, temperature=0.3)
            payload = InsightsEngine._parse_json(raw)

        if payload is None:
            logger.error(f"[enrich] unparseable JSON for doc_id={doc_id}: {raw[:300]!r}")
            raise ValueError("Failed to parse enrichment JSON from LLM")

        _EXPECTED = {"summary", "sentiment", "classification", "entities"}
        if not any(k in payload for k in _EXPECTED):
            logger.error(f"[enrich] LLM returned non-enrichment JSON keys={list(payload.keys())} doc_id={doc_id}")
            raise ValueError(f"LLM did not enrich the document (got keys: {list(payload.keys())})")

        payload["iocs"] = extract_iocs(text)

        location_names = payload.pop("locations", []) or []
        if isinstance(location_names, list) and location_names:
            unique_names = list(set([n.strip() for n in location_names if isinstance(n, str) and n.strip()]))[:10]
            geocoded = []
            with ThreadPoolExecutor(max_workers=3) as executor:
                future_to_name = {executor.submit(geocode_location, name): name for name in unique_names}
                for future in as_completed(future_to_name):
                    res = future.result()
                    if res:
                        geocoded.append(res)
            payload["locations"] = geocoded

        doc_lang = (payload.get("language") or "en").lower()
        if doc_lang not in ("ro", "ron", "rum"):
            try:
                t_msgs, t_sys = builder.build_translation_messages(text[:3000])
                t_raw = llm.complete_json(t_msgs, t_sys)
                t_data = InsightsEngine._parse_json(t_raw)
                if not (t_data and t_data.get("text")):
                    logger.warning(f"[enrich] Translation parse fail for doc_id={doc_id}, retrying with temp=0.3...")
                    t_raw = llm.complete_json(t_msgs, t_sys, temperature=0.3)
                    t_data = InsightsEngine._parse_json(t_raw)
                if t_data and t_data.get("text"):
                    payload["translation"] = t_data["text"]
            except Exception as te:
                logger.warning(f"[enrich] Translation failed for doc_id={doc_id}: {te}")

        with get_db() as db:
            row = db.query(DocumentEnrichment).filter_by(doc_id=doc_id, datasource=datasource).first()
            if row:
                row.status = "complete"
                row.payload = payload
                row.error = None
                db.commit()
                logger.info(f"[enrich] Complete: doc_id={doc_id}", "magenta")

    except Exception as e:
        logger.error(f"[enrich] Failed doc_id={doc_id}: {e}", exc_info=True)
        try:
            with get_db() as db:
                row = db.query(DocumentEnrichment).filter_by(doc_id=doc_id, datasource=datasource).first()
                if row:
                    row.status = "error"
                    row.error = str(e)
                    db.commit()
        except Exception as db_err:
            logger.error(f"[enrich] DB error-update failed: {db_err}")
