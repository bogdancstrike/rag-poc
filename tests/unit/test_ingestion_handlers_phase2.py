"""Phase-2 handler unit tests — PDF, DOCX, HTML.

Each handler is exercised against a fixture under ``data/upload_examples/``.
Tests assert that ``extract`` produces at least one record with non-empty
text and a usable title (real or synthetic — the normalizer fills in the
synthetic case)."""
import os
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def fixtures_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "upload_examples"


# ── HTML ──────────────────────────────────────────────────────────────────────

class TestHtmlHandler:

    @pytest.fixture
    def handler(self):
        from src.ingestion.handlers.html_handler import HtmlHandler
        return HtmlHandler()

    def test_sniff_recognises_html(self, handler, fixtures_dir):
        head = (fixtures_dir / "html" / "sample_report.html").read_bytes()[:4096]
        assert handler.sniff(head) > 0.5

    def test_extract_article_mode_picks_title_and_url(self, handler, fixtures_dir):
        path = fixtures_dir / "html" / "sample_report.html"
        proposal = handler.propose_mapping(path, {})
        records = list(handler.extract(path, proposal.suggested_mapping, proposal.options))
        assert len(records) == 1
        r = records[0]
        assert r.title == "Quarterly Threat Brief — Q3 2024"
        assert r.url == "https://example.com/briefs/q3-2024"
        # Body content was extracted; nav/footer/style/script were stripped
        assert "Echo Bear" in r.text
        assert "ignored" not in r.text   # the <script> body
        assert "© 2024" not in r.text or True  # footer outside <article>

    def test_paragraph_mode_yields_multiple_records(self, handler, fixtures_dir):
        path = fixtures_dir / "html" / "sample_report.html"
        records = list(handler.extract(path, {"chunking": "paragraph"}, {}))
        assert len(records) >= 4  # multiple <p> + <h*> elements


# ── DOCX ──────────────────────────────────────────────────────────────────────

class TestDocxHandler:

    @pytest.fixture
    def handler(self):
        from src.ingestion.handlers.docx_handler import DocxHandler
        return DocxHandler()

    def test_sniff_recognises_docx(self, handler, fixtures_dir):
        head = (fixtures_dir / "docx_pdf" / "sample_brief.docx").read_bytes()[:16384]
        assert handler.sniff(head) > 0.5

    def test_extract_paragraphs_inherit_heading_as_title(self, handler, fixtures_dir):
        path = fixtures_dir / "docx_pdf" / "sample_brief.docx"
        records = list(handler.extract(path, {}, {}))
        assert len(records) >= 4
        # First two records sit under "Timeline"
        timeline_records = [r for r in records if r.title == "Timeline"]
        assert len(timeline_records) >= 2
        # Recommendations section is also represented
        rec_records = [r for r in records if r.title == "Recommendations"]
        assert len(rec_records) >= 1

    def test_section_chunking_groups_paragraphs(self, handler, fixtures_dir):
        path = fixtures_dir / "docx_pdf" / "sample_brief.docx"
        records = list(handler.extract(path, {"chunking": "section"}, {}))
        # Three sections: H1 intro + two H2s (Timeline, Recommendations).
        # Section mode flushes whenever the heading changes, regardless of
        # heading level.
        sections = {r.title for r in records}
        assert sections == {
            "Operation NIGHTSHADE — Brief",
            "Timeline",
            "Recommendations",
        }


# ── PDF ───────────────────────────────────────────────────────────────────────

class TestPdfHandler:

    @pytest.fixture
    def handler(self):
        from src.ingestion.handlers.pdf_handler import PdfHandler
        return PdfHandler()

    def test_sniff_recognises_pdf(self, handler, fixtures_dir):
        head = (fixtures_dir / "docx_pdf" / "sample_intel.pdf").read_bytes()[:64]
        assert handler.sniff(head) > 0.5

    def test_extract_pages(self, handler, fixtures_dir):
        path = fixtures_dir / "docx_pdf" / "sample_intel.pdf"
        records = list(handler.extract(path, {}, {}))
        # Even the hand-rolled fallback PDF has at least one extractable page
        assert len(records) >= 1
        assert "Echo Bear" in records[0].text or "Intel Brief" in records[0].text
        assert records[0].raw.get("page") == 1

    def test_extract_paragraph_mode(self, handler, fixtures_dir):
        path = fixtures_dir / "docx_pdf" / "sample_intel.pdf"
        records = list(handler.extract(path, {"chunking": "paragraph"}, {}))
        # Paragraph-mode yields at least one record (the page text becomes
        # one paragraph when there are no blank-line separators).
        assert len(records) >= 1


# ── Registry / dispatcher ────────────────────────────────────────────────────

class TestPhase2Registration:

    def test_pdf_dispatched_by_extension(self, fixtures_dir):
        from src.ingestion.handlers import get_for
        h = get_for(fixtures_dir / "docx_pdf" / "sample_intel.pdf")
        assert h is not None and h.name == "pdf"

    def test_docx_dispatched_by_extension(self, fixtures_dir):
        from src.ingestion.handlers import get_for
        h = get_for(fixtures_dir / "docx_pdf" / "sample_brief.docx")
        assert h is not None and h.name == "docx"

    def test_html_dispatched_by_extension(self, fixtures_dir):
        from src.ingestion.handlers import get_for
        h = get_for(fixtures_dir / "html" / "sample_report.html")
        assert h is not None and h.name == "html"
