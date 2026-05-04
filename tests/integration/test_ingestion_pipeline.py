"""Integration tests: pipeline.run_parse + pipeline.run_index against the
example fixtures with a mocked ES client + LLM mapper. Covers the
parser-profile reuse path (the headline feature).

No real Kafka / ES required. SQLite in-memory + monkey-patched bulk helper +
LLM call stubbed out to skip ingest-LLM-traffic.
"""
import io
import os
import shutil
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
# Ensure the storage layer writes to a sandbox under tmp/.
_TEST_UPLOADS = Path(__file__).resolve().parent / "_uploads_test"
os.environ["UPLOADS_DIR"] = str(_TEST_UPLOADS)

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def fixtures_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "upload_examples"


@pytest.fixture(autouse=True)
def fresh_db(tmp_path_factory, monkeypatch):
    """In-memory SQLite + isolated uploads dir per test."""
    from src.config import Config
    upl = tmp_path_factory.mktemp("uploads")
    monkeypatch.setattr(Config, "UPLOADS_DIR", str(upl), raising=False)
    # Force the storage singleton to pick up the new root
    import src.ingestion.storage as storage_mod
    monkeypatch.setattr(storage_mod, "_storage", None, raising=False)

    from src.core.db import init_db, get_engine, Base
    init_db()
    yield
    Base.metadata.drop_all(bind=get_engine())


@pytest.fixture
def fake_es(monkeypatch):
    """Stub ESClient + es_helpers.bulk so we can assert on documents
    actually shipped to ES without running a real cluster."""
    indexed: list[dict] = []

    class _FakeClient:
        class indices:
            @staticmethod
            def refresh(index): pass
        @staticmethod
        def delete_by_query(*a, **k): pass

    class FakeES:
        def __init__(self):
            self._client = _FakeClient()
        def create_index(self, name, mapping=None): return False
        def invalidate_vector_cache(self, name): pass

    def fake_bulk(client, actions, **kwargs):
        # Materialize the generator so we count documents
        actions = list(actions)
        for a in actions:
            indexed.append(a)
        return len(actions), []

    monkeypatch.setattr("src.retrieval.es_client.ESClient", FakeES)
    monkeypatch.setattr("src.ingestion.pipeline.es_helpers.bulk", fake_bulk)
    return indexed


@pytest.fixture
def stub_llm(monkeypatch):
    """Skip the LLM mapping refinement — fall through to heuristic only."""
    def fake_refine(handler_name, columns, samples, heuristic):
        return {
            "mapping": heuristic, "confidence": 0.5,
            "rationale": "LLM stubbed in test", "source": "heuristic",
        }
    monkeypatch.setattr("src.ingestion.llm_mapping.refine_mapping", fake_refine)


@pytest.fixture
def stub_publish(monkeypatch):
    """Avoid hitting Kafka or the thread-fallback executor."""
    monkeypatch.setattr("src.tasking.producer.publish_task", lambda task: True)
    monkeypatch.setattr("src.ingestion.service.publish_task",
                        lambda task: True, raising=False)
    monkeypatch.setattr("src.ingestion.pipeline.__dict__", pipeline_dict := __import__(
        "src.ingestion.pipeline", fromlist=["*"]).__dict__, raising=False)


@pytest.fixture
def make_investigation():
    """Create a real Investigation row + a fake ES index name."""
    from src.investigations.service import create_investigation
    return lambda name="test-inv": create_investigation(name=name)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _upload_via_service(investigation_id: str, path: Path, mime: str = "text/csv") -> dict:
    """Drive ingestion.service.create_upload with the file's bytes."""
    from src.ingestion.service import create_upload
    with path.open("rb") as f:
        return create_upload(investigation_id, path.name, f, mime_type=mime)


# ── Tests ────────────────────────────────────────────────────────────────────

def test_full_pipeline_csv_parse_and_review(
    fixtures_dir, make_investigation, fake_es, stub_llm, monkeypatch,
):
    """run_parse on a fresh CSV → status mapping_review with proposal."""
    # Stub the producer so create_upload doesn't actually queue.
    monkeypatch.setattr("src.ingestion.service.publish_task",
                        lambda task: True, raising=False)
    inv = make_investigation()
    upload = _upload_via_service(
        inv["id"], fixtures_dir / "csv" / "leak_users_2024.csv",
    )

    from src.ingestion.pipeline import run_parse
    run_parse(upload["id"])

    from src.ingestion.service import get_upload
    rec = get_upload(upload["id"])
    assert rec["status"] == "mapping_review"
    assert rec["handler_name"] == "csv"
    assert rec["proposed_mapping"] is not None
    assert rec["proposed_mapping"]["fingerprint"] is not None


def test_profile_cache_skips_review_for_same_structure(
    fixtures_dir, make_investigation, fake_es, stub_llm, monkeypatch,
):
    """Upload leak_users_2024 + confirm a profile, then upload leak_users_2025.
    The second upload's run_parse should hit the profile cache and skip
    mapping_review — proving the headline feature."""
    # Stub publish_task on both modules so nothing leaves the test process.
    monkeypatch.setattr("src.ingestion.service.publish_task",
                        lambda task: True, raising=False)
    monkeypatch.setattr("src.ingestion.pipeline.publish_task",
                        lambda task: True, raising=False)

    inv = make_investigation()
    # ── First file: parse → confirm with save_as_profile=True
    a = _upload_via_service(
        inv["id"], fixtures_dir / "csv" / "leak_users_2024.csv",
    )
    from src.ingestion.pipeline import run_parse
    run_parse(a["id"])

    from src.ingestion.service import confirm_mapping, get_upload
    rec = get_upload(a["id"])
    proposed = rec["proposed_mapping"]["mapping"]
    confirmed = confirm_mapping(
        a["id"], mapping=proposed, options={}, save_as_profile=True,
        profile_name="leak-users-format",
    )
    assert confirmed["status"] == "indexing"
    assert confirmed["profile_id"] is not None

    # ── Second file: run_parse should pick the profile and skip review
    b = _upload_via_service(
        inv["id"], fixtures_dir / "csv" / "leak_users_2025.csv",
    )
    # Spy: track whether refine_mapping is called for the second file.
    calls = {"n": 0}
    real_refine = __import__(
        "src.ingestion.llm_mapping", fromlist=["refine_mapping"]
    ).refine_mapping
    def spy_refine(*args, **kwargs):
        calls["n"] += 1
        return real_refine(*args, **kwargs)
    monkeypatch.setattr("src.ingestion.pipeline.llm_mapping.refine_mapping", spy_refine)

    run_parse(b["id"])
    rec_b = get_upload(b["id"])
    # NOTE: run_parse calls run_index inline on a profile cache hit, so the
    # status will be "complete" after parse if the index path runs cleanly.
    assert rec_b["status"] in ("indexing", "complete")
    assert rec_b["profile_id"] == confirmed["profile_id"]
    # And critically: the LLM refinement was NOT consulted for the second file
    assert calls["n"] == 0


def test_run_index_streams_into_es(
    fixtures_dir, make_investigation, fake_es, stub_llm, monkeypatch,
):
    """Confirm that run_index emits one bulk action per record."""
    monkeypatch.setattr("src.ingestion.service.publish_task",
                        lambda task: True, raising=False)
    monkeypatch.setattr("src.ingestion.pipeline.publish_task",
                        lambda task: True, raising=False)

    inv = make_investigation()
    upload = _upload_via_service(
        inv["id"], fixtures_dir / "csv" / "support_tickets.csv",
        mime="text/csv",
    )
    from src.ingestion.pipeline import run_parse
    from src.ingestion.service import confirm_mapping, get_upload

    run_parse(upload["id"])
    rec = get_upload(upload["id"])
    proposed = rec["proposed_mapping"]["mapping"]
    confirm_mapping(upload["id"], mapping=proposed, options={})
    # ``confirm_mapping`` already kicks ingest_continue via publish_task, but
    # we stubbed that — call run_index directly to drive the index stage.
    from src.ingestion.pipeline import run_index
    run_index(upload["id"])

    # support_tickets.csv has 8 rows
    assert len(fake_es) == 8
    # Each action is an upsert into the investigation index
    inv_index = inv["index_name"]
    for action in fake_es:
        assert action["_index"] == inv_index
        assert "_id" in action
        # text was the longest-column heuristic → "body"
        assert action["_source"]["text"]
        assert action["_source"]["source"].startswith("upload:support_tickets.csv#")

    final = get_upload(upload["id"])
    assert final["status"] == "complete"
    assert final["indexed_count"] == 8


def test_duplicate_upload_returns_existing_id(
    fixtures_dir, make_investigation, monkeypatch,
):
    """Same bytes uploaded twice → DuplicateUploadError carrying the first id."""
    monkeypatch.setattr("src.ingestion.service.publish_task",
                        lambda task: True, raising=False)
    inv = make_investigation()
    path = fixtures_dir / "csv" / "leak_users_2024.csv"
    a = _upload_via_service(inv["id"], path)

    from src.ingestion.service import DuplicateUploadError
    with pytest.raises(DuplicateUploadError) as exc:
        _upload_via_service(inv["id"], path)
    assert exc.value.existing_id == a["id"]
