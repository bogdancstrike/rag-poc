"""E2E tests for the file-upload flow over HTTP.

Requires the backend running on ``localhost:5100`` with Postgres + ES + Kafka
(or thread fallback) up. Skipped automatically when the backend is down.

Exercises:
  - GET  /v1/uploads/formats
  - POST /v1/investigations/<id>/uploads (multipart)
  - GET  /v1/investigations/<id>/uploads
  - POST /v1/uploads/<id>/confirm
  - GET  /v1/uploads/<id>
  - GET  /v1/uploads/<id>/download
  - DELETE /v1/uploads/<id>?purge_es=true
  - GET  /v1/parser-profiles  (after confirming with save_as_profile)

Drives the leak_users_2024 → leak_users_2025 reuse path end-to-end.
"""
import time
from pathlib import Path

import pytest
import requests


BASE = "http://localhost:5100/rag"
FIXTURES = Path(__file__).resolve().parents[2] / "data" / "upload_examples"


def backend_available() -> bool:
    try:
        r = requests.get(f"{BASE}/liveness", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not backend_available(), reason="Backend not available at localhost:5100",
)


def _wait_for_status(file_id: str, target: str | tuple[str, ...],
                     timeout: float = 60.0, poll: float = 1.0) -> dict:
    """Poll an upload until it reaches one of the target statuses."""
    targets = (target,) if isinstance(target, str) else tuple(target)
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = requests.get(f"{BASE}/v1/uploads/{file_id}", timeout=10)
        assert r.status_code == 200, r.text
        last = r.json()
        if last["status"] in targets:
            return last
        if last["status"] == "error":
            pytest.fail(f"upload errored: {last.get('error')}")
        time.sleep(poll)
    pytest.fail(f"timed out waiting for {targets}; last status={last and last['status']}")


def _create_investigation(name: str) -> dict:
    r = requests.post(
        f"{BASE}/v1/investigations",
        json={"name": name, "search_ids": []},
        timeout=10,
    )
    assert r.status_code == 202, r.text
    inv = r.json()
    # Poll until the index is built (status=ready or ready_with_vectors).
    for _ in range(60):
        r = requests.get(f"{BASE}/v1/investigations/{inv['id']}", timeout=10)
        if r.json()["status"] in ("ready", "ready_with_vectors"):
            return r.json()
        time.sleep(1)
    pytest.fail("investigation never became ready")


def _delete_investigation(inv_id: str) -> None:
    requests.delete(f"{BASE}/v1/investigations/{inv_id}", timeout=20)


# ── Tests ────────────────────────────────────────────────────────────────────

class TestUploadsE2E:

    def test_accepted_formats_endpoint(self):
        r = requests.get(f"{BASE}/v1/uploads/formats", timeout=5)
        assert r.status_code == 200
        body = r.json()
        assert "handlers" in body and "accept_string" in body
        names = {h["name"] for h in body["handlers"]}
        assert {"csv", "jsonl", "xlsx", "text"}.issubset(names)
        assert ".csv" in body["accept_string"]

    def test_full_upload_confirm_index_cycle(self):
        """Upload leak_users_2024.csv, confirm mapping with save_as_profile=True,
        wait until indexing completes, then upload leak_users_2025.csv and
        verify the parser profile was reused (no mapping_review pause).
        """
        # Idempotency: a previous run may have saved a profile that would
        # cause the *first* upload to also skip mapping_review. Wipe any
        # pre-existing CSV profiles whose name matches our test marker.
        prof = requests.get(f"{BASE}/v1/parser-profiles?handler=csv", timeout=10).json()
        for p in prof.get("profiles", []):
            if (p.get("name") or "").startswith("e2e-leak-format"):
                requests.delete(f"{BASE}/v1/parser-profiles/{p['id']}", timeout=10)
        # Belt-and-braces: also drop any profile whose mapping looks like ours
        # (no name, but same shape). Cheap to delete; safe in a test DB.
        for p in prof.get("profiles", []):
            mapping = p.get("mapping") or {}
            if mapping.get("text") == "password_hash" or {
                "user_id", "email", "password_hash"
            }.issubset(set(mapping.values())):
                requests.delete(f"{BASE}/v1/parser-profiles/{p['id']}", timeout=10)

        inv = _create_investigation("e2e-upload-test")
        try:
            # ── First file ── upload + wait for mapping_review
            with (FIXTURES / "csv" / "leak_users_2024.csv").open("rb") as fh:
                r = requests.post(
                    f"{BASE}/v1/investigations/{inv['id']}/uploads",
                    files={"file": ("leak_users_2024.csv", fh, "text/csv")},
                    timeout=30,
                )
            assert r.status_code == 202, r.text
            file_a = r.json()
            review_a = _wait_for_status(file_a["id"], "mapping_review", timeout=60)
            mapping_a = review_a["proposed_mapping"]["mapping"]
            assert mapping_a["text"]   # heuristic always picks something

            # Confirm + save profile
            r = requests.post(
                f"{BASE}/v1/uploads/{file_a['id']}/confirm",
                json={
                    "mapping": mapping_a, "options": {},
                    "save_as_profile": True, "name": "e2e-leak-format",
                },
                timeout=10,
            )
            assert r.status_code == 202, r.text
            done_a = _wait_for_status(file_a["id"], "complete", timeout=90)
            assert done_a["indexed_count"] == 10

            # Profile must now exist
            r = requests.get(f"{BASE}/v1/parser-profiles?handler=csv", timeout=10)
            assert r.status_code == 200
            profiles = r.json()["profiles"]
            assert any(p["name"] == "e2e-leak-format" for p in profiles)

            # ── Second file ── upload should skip mapping_review
            with (FIXTURES / "csv" / "leak_users_2025.csv").open("rb") as fh:
                r = requests.post(
                    f"{BASE}/v1/investigations/{inv['id']}/uploads",
                    files={"file": ("leak_users_2025.csv", fh, "text/csv")},
                    timeout=30,
                )
            assert r.status_code == 202, r.text
            file_b = r.json()
            done_b = _wait_for_status(file_b["id"], "complete", timeout=90)
            assert done_b["indexed_count"] == 10
            assert done_b["profile_id"] is not None
            # NOTE: profile_id may be None on a slow consumer if confirm_mapping
            # hadn't yet linked the profile to the first file before the second
            # arrived; the assertion above is the strict version.

            # Listing endpoint sees both
            r = requests.get(f"{BASE}/v1/investigations/{inv['id']}/uploads", timeout=10)
            assert r.status_code == 200
            ids = {u["id"] for u in r.json()["uploads"]}
            assert {file_a["id"], file_b["id"]} == ids

            # Download original
            r = requests.get(f"{BASE}/v1/uploads/{file_a['id']}/download",
                             timeout=10, stream=True)
            assert r.status_code == 200
            data = b"".join(r.iter_content(chunk_size=8192))
            assert data.startswith(b"user_id,")

            # Duplicate upload → 409
            with (FIXTURES / "csv" / "leak_users_2024.csv").open("rb") as fh:
                r = requests.post(
                    f"{BASE}/v1/investigations/{inv['id']}/uploads",
                    files={"file": ("leak_users_2024.csv", fh, "text/csv")},
                    timeout=30,
                )
            assert r.status_code == 409
            assert r.json().get("existing_id") == file_a["id"]

            # Cleanup uploads (purge ES too)
            for fid in (file_a["id"], file_b["id"]):
                r = requests.delete(
                    f"{BASE}/v1/uploads/{fid}?purge_es=true", timeout=20,
                )
                assert r.status_code == 200
        finally:
            _delete_investigation(inv["id"])

    def test_jsonl_upload_no_mapping_needed_when_obvious(self):
        """A JSONL file with a clear `text` key should still go through the
        review step (Phase 1 always reviews unless a profile exists), but
        the heuristic must pick the right column."""
        inv = _create_investigation("e2e-jsonl-test")
        try:
            with (FIXTURES / "jsonl" / "tweets.jsonl").open("rb") as fh:
                r = requests.post(
                    f"{BASE}/v1/investigations/{inv['id']}/uploads",
                    files={"file": ("tweets.jsonl", fh, "application/x-ndjson")},
                    timeout=30,
                )
            assert r.status_code == 202
            fid = r.json()["id"]
            review = _wait_for_status(fid, "mapping_review", timeout=60)
            assert review["handler_name"] == "jsonl"
            assert review["proposed_mapping"]["mapping"]["text"] == "text"
        finally:
            _delete_investigation(inv["id"])
