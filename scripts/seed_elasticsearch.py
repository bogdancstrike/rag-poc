"""Seed Elasticsearch with realistic QSINT intelligence documents using Faker.

Run: python3 scripts/seed_elasticsearch.py
     python3 scripts/seed_elasticsearch.py --count 30000 --batch 500
     python3 scripts/seed_elasticsearch.py --count 1000 --clear
"""
import argparse
import sys
import uuid
from datetime import timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from faker import Faker
from elasticsearch.helpers import bulk

from src.datasource.es_client import ESClient

fake = Faker(['en_US', 'en_GB', 'ru_RU', 'de_DE', 'fr_FR'])

# ── Vocabulary ──────────────────────────────────────────────────────────────────

TOPICS = [
    "disinformation campaign", "social media manipulation", "bot network",
    "coordinated inauthentic behaviour", "election interference",
    "state-sponsored influence operation", "deepfake content",
    "narrative amplification", "astroturfing campaign", "troll farm activity",
    "propaganda distribution", "information warfare", "cyber espionage",
    "hacktivism", "data leak", "phishing campaign", "ransomware attack",
    "network intrusion", "supply chain attack", "credential stuffing",
    "watering hole attack", "spearphishing", "DDoS campaign", "zero-day exploit",
    "malware distribution", "cryptojacking", "insider threat", "false flag operation",
]

ENTITIES = [
    "Kremlin-linked actors", "APT28", "APT29", "Sandworm", "Fancy Bear",
    "Internet Research Agency", "GRU Unit 26165", "GRU Unit 74455",
    "FVEY alliance", "NSA", "GCHQ", "BND", "FSB", "SVR",
    "Lazarus Group", "Cozy Bear", "Equation Group", "Charming Kitten",
    "Anonymous", "LockBit", "Conti Group", "REvil", "DarkSide",
    "NATO Cyber Centre", "ENISA", "CISA", "Cybersecurity Alliance",
    "CloudStrike", "Mandiant", "Recorded Future",
]

PLATFORMS = [
    "Twitter/X", "Telegram", "Facebook", "TikTok", "Reddit",
    "VK", "WeChat", "Discord", "Instagram", "YouTube",
    "LinkedIn", "4chan", "Parler", "Truth Social", "Gab",
]

REGIONS = [
    "Eastern Europe", "Western Europe", "North America", "Asia-Pacific",
    "Middle East", "Latin America", "Sub-Saharan Africa", "Central Asia",
    "Southeast Asia", "Nordic countries", "Balkans", "Caucasus", "Global",
]

SENTIMENTS  = ["hostile", "neutral", "supportive", "ambiguous", "inflammatory"]
OBJECTIVES  = [
    "sow discord", "undermine trust in institutions", "amplify existing tensions",
    "interfere with electoral process", "promote pro-government narratives",
    "suppress opposition voices", "recruit sympathisers", "exfiltrate data",
    "extort financial gain", "disrupt critical infrastructure",
]
INDICATORS  = [
    "abnormal posting velocity", "coordinated account creation",
    "identical message templates", "inorganic engagement patterns",
    "use of proxy infrastructure", "VPN endpoint clustering",
    "cross-platform coordination", "hashtag hijacking", "bot-like activity",
]

LANGUAGES = ["English", "Russian", "German", "French", "Arabic", "Chinese",
             "Spanish", "Ukrainian", "Polish", "Turkish"]


def generate_doc(idx: int) -> dict:
    """Generate a rich QSINT intelligence document using Faker."""
    topic       = fake.random_element(TOPICS)
    entity      = fake.random_element(ENTITIES)
    platform    = fake.random_element(PLATFORMS)
    region      = fake.random_element(REGIONS)
    sentiment   = fake.random_element(SENTIMENTS)
    objective   = fake.random_element(OBJECTIVES)
    indicator1  = fake.random_element(INDICATORS)
    indicator2  = fake.random_element(INDICATORS)
    language    = fake.random_element(LANGUAGES)
    confidence  = fake.random_int(min=45, max=99)
    account_cnt = fake.random_int(min=10, max=200_000)
    days_ago    = fake.random_int(min=0, max=180)
    ts          = (fake.date_time_this_year(tzinfo=timezone.utc) - timedelta(days=days_ago)).isoformat()

    # Build a detailed multi-paragraph report
    title = f"[QSINT-{idx:06d}] {topic.title()} — {entity}"
    body  = (
        f"**Case ID:** QSINT-{idx:06d}  \n"
        f"**Classification:** RESTRICTED  \n"
        f"**Analyst:** {fake.name()}  \n\n"

        f"## Executive Summary\n"
        f"A {sentiment} {topic} has been identified on {platform}, attributed with "
        f"{confidence}% confidence to {entity}. The operation targets audiences in "
        f"{region} with the primary objective to {objective}.\n\n"

        f"## Technical Indicators\n"
        f"Analysts identified {indicator1} and {indicator2} as primary technical "
        f"indicators. Approximately {account_cnt:,} accounts are involved. "
        f"Infrastructure analysis points to {fake.ipv4_public()} as a key endpoint.\n\n"

        f"## Narrative Analysis\n"
        f"{fake.paragraph(nb_sentences=4)} "
        f"The dominant language is {language}. Key hashtags include "
        f"#{fake.word()}, #{fake.word()}, and #{fake.word()}.\n\n"

        f"## Attribution\n"
        f"TTPs overlap with previously documented campaigns by {entity}. "
        f"Confidence in attribution: {confidence}%. "
        f"{fake.paragraph(nb_sentences=2)}\n\n"

        f"## Recommendations\n"
        f"- Immediate monitoring of {platform} for further activity.\n"
        f"- Coordinate with {fake.random_element(['CERT', 'NCSC', 'ENISA', 'CISA'])} for response.\n"
        f"- Request takedown via {platform} abuse reporting.\n"
        f"- Cross-reference with existing {fake.random_element(['APT', 'CERT', 'TLP'])} feeds.\n"
    )

    return {
        "title":       title,
        "text":        body,
        "topic":       topic,
        "entity":      entity,
        "platform":    platform,
        "region":      region,
        "sentiment":   sentiment,
        "objective":   objective,
        "confidence":  confidence,
        "account_count": account_cnt,
        "language":    language,
        "tags":        fake.random_elements(TOPICS, length=3, unique=True),
        "analyst":     fake.name(),
        "source":      "qsint-seed",
        "created_at":  ts,
        "ip_indicator": fake.ipv4_public(),
    }


def bulk_index(client: ESClient, docs: list[dict]) -> tuple[int, int]:
    """Bulk-index a batch of docs. Returns (success_count, error_count)."""
    actions = [
        {
            "_index": client._index,
            "_id":    str(uuid.uuid4()),
            "_source": doc,
        }
        for doc in docs
    ]
    ok, errors = bulk(client._client, actions, raise_on_error=False)
    return ok, len(errors)


def main():
    parser = argparse.ArgumentParser(description="Seed Elasticsearch with QSINT sample data")
    parser.add_argument("--count", type=int, default=30_000, help="Number of docs to index (default: 30000)")
    parser.add_argument("--batch", type=int, default=500,    help="Bulk batch size (default: 500)")
    parser.add_argument("--clear", action="store_true",      help="Delete index before seeding")
    args = parser.parse_args()

    client = ESClient()
    if not client.test_connection():
        print("ERROR: Cannot connect to Elasticsearch at", client._client.transport.hosts)
        sys.exit(1)

    if args.clear:
        try:
            client._client.indices.delete(index=client._index)
            print(f"Deleted index '{client._index}'")
        except Exception:
            pass

    client.ensure_index()

    total_ok = 0
    total_err = 0
    print(f"Seeding {args.count:,} documents into '{client._index}' (batch size: {args.batch})...")

    for start in range(0, args.count, args.batch):
        end   = min(start + args.batch, args.count)
        batch = [generate_doc(start + i + 1) for i in range(end - start)]
        ok, err = bulk_index(client, batch)
        total_ok  += ok
        total_err += err
        print(f"  [{end:>6,}/{args.count:,}] indexed {ok}, errors {err}")

    # Refresh index so documents are immediately searchable
    client._client.indices.refresh(index=client._index)
    print(f"\nDone: {total_ok:,} documents indexed, {total_err} errors.")
    print(f"Index stats: {client.get_index_stats()}")


if __name__ == "__main__":
    main()
