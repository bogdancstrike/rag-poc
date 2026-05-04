"""Unit tests for tasks_analytics_handler and related timing logic.

Uses SQLite in-memory DB — no real PostgreSQL or Kafka required.
"""
import os
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_insight_row(
    ds="ds1", insight_type="summary", status="complete",
    generated_at=None, started_at=None, updated_at=None,
    error=None, payload=None, retry_count=0,
):
    """Build a mock InsightsCache row."""
    now = datetime.now(timezone.utc)
    row = MagicMock()
    row.datasource   = ds
    row.insight_type = insight_type
    row.status       = status
    row.generated_at = generated_at or now - timedelta(seconds=30)
    row.started_at   = started_at   or now - timedelta(seconds=25)
    row.updated_at   = updated_at   or now - timedelta(seconds=5)
    row.error        = error
    row.payload      = payload
    row.retry_count  = retry_count
    row.sample_hash  = "abc123"
    return row


def _make_enrich_row(
    ds="ds1", doc_id="doc-1", status="complete",
    generated_at=None, started_at=None, updated_at=None,
    error=None, payload=None, retry_count=0,
):
    now = datetime.now(timezone.utc)
    row = MagicMock()
    row.datasource   = ds
    row.doc_id       = doc_id
    row.status       = status
    row.generated_at = generated_at or now - timedelta(seconds=60)
    row.started_at   = started_at   or now - timedelta(seconds=50)
    row.updated_at   = updated_at   or now - timedelta(seconds=10)
    row.error        = error
    row.payload      = payload
    row.retry_count  = retry_count
    return row


# ── Tests for analytics handler output shape ─────────────────────────────────

class TestTasksAnalyticsHandler:

    def _call_handler(self, insight_rows=None, enrich_rows=None, ds_filter="", cat_filter=""):
        """Directly exercise tasks_analytics_handler logic with mocked DB rows."""
        from src.api.endpoints import tasks_analytics_handler

        insight_rows = insight_rows or []
        enrich_rows  = enrich_rows  or []

        mock_db = MagicMock()

        def mock_query(model):
            from src.insights.models import InsightsCache
            from src.enrichment.models import DocumentEnrichment
            q = MagicMock()
            if model is InsightsCache:
                q.filter.return_value = q
                q.all.return_value = insight_rows
            else:
                q.filter.return_value = q
                q.all.return_value = enrich_rows
            return q

        mock_db.query = mock_query

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        mock_request = MagicMock()
        mock_request.args.get = lambda key, default="": {
            "datasource": ds_filter,
            "category":   cat_filter,
        }.get(key, default)

        with patch("src.api.endpoints.flask_request", mock_request):
            # ``get_db`` is imported lazily inside the handler — patch the
            # source module so any reference path picks up the mock.
            with patch("src.core.db.get_db", return_value=mock_ctx):
                result, status_code = tasks_analytics_handler(None, None, mock_request)

        return result, status_code

    def test_returns_200(self):
        result, code = self._call_handler()
        assert code == 200

    def test_response_has_all_required_keys(self):
        result, _ = self._call_handler()
        assert "timing"      in result
        assert "throughput"  in result
        assert "status_dist" in result
        assert "type_dist"   in result
        assert "time_series" in result
        assert "total_tasks" in result

    def test_throughput_has_all_windows(self):
        result, _ = self._call_handler()
        assert set(result["throughput"].keys()) >= {"5m", "1h", "12h", "1d", "7d"}

    def test_total_tasks_counts_both_categories(self):
        rows_i = [_make_insight_row(), _make_insight_row(insight_type="graph")]
        rows_e = [_make_enrich_row(), _make_enrich_row(doc_id="doc-2")]
        result, _ = self._call_handler(insight_rows=rows_i, enrich_rows=rows_e)
        assert result["total_tasks"] == 4

    def test_status_distribution_correct(self):
        rows = [
            _make_insight_row(status="complete"),
            _make_insight_row(status="complete", insight_type="graph"),
            _make_insight_row(status="error",    insight_type="stats"),
        ]
        result, _ = self._call_handler(insight_rows=rows)
        assert result["status_dist"]["complete"] == 2
        assert result["status_dist"]["error"]    == 1

    def test_type_distribution_correct(self):
        rows = [
            _make_insight_row(insight_type="summary"),
            _make_insight_row(insight_type="summary"),
            _make_insight_row(insight_type="graph"),
        ]
        result, _ = self._call_handler(insight_rows=rows)
        assert result["type_dist"]["summary"] == 2
        assert result["type_dist"]["graph"]   == 1

    def test_timing_includes_avg_values(self):
        now = datetime.now(timezone.utc)
        row = _make_insight_row(
            generated_at=now - timedelta(seconds=40),
            started_at=now   - timedelta(seconds=30),
            updated_at=now   - timedelta(seconds=5),
            status="complete",
        )
        result, _ = self._call_handler(insight_rows=[row])
        assert len(result["timing"]) == 1
        t = result["timing"][0]
        assert t["avg_queue_ms"] is not None
        assert t["avg_exec_ms"]  is not None
        assert t["avg_total_ms"] is not None
        # queue = 10s, exec = 25s, total = 35s
        assert abs(t["avg_queue_ms"] - 10_000) < 500
        assert abs(t["avg_exec_ms"]  - 25_000) < 500
        assert abs(t["avg_total_ms"] - 35_000) < 500

    def test_throughput_5m_counts_recent_complete_tasks(self):
        now = datetime.now(timezone.utc)
        recent_row  = _make_insight_row(updated_at=now - timedelta(minutes=2), status="complete")
        old_row     = _make_insight_row(updated_at=now - timedelta(minutes=10), status="complete", insight_type="graph")
        pending_row = _make_insight_row(status="pending", insight_type="stats")
        result, _ = self._call_handler(insight_rows=[recent_row, old_row, pending_row])
        # Only recent_row is within 5m window and complete
        assert result["throughput"]["5m"] == 1

    def test_empty_db_returns_zeros(self):
        result, _ = self._call_handler(insight_rows=[], enrich_rows=[])
        assert result["total_tasks"] == 0
        assert all(v == 0 for v in result["throughput"].values())
        assert result["status_dist"] == {}
        assert result["timing"] == []

    def test_time_series_sorted_by_timestamp(self):
        now = datetime.now(timezone.utc)
        rows = [
            _make_insight_row(updated_at=now - timedelta(hours=5), status="complete"),
            _make_insight_row(updated_at=now - timedelta(hours=2), status="complete", insight_type="graph"),
            _make_insight_row(updated_at=now - timedelta(hours=1), status="complete", insight_type="stats"),
        ]
        result, _ = self._call_handler(insight_rows=rows)
        ts_list = [p["ts"] for p in result["time_series"]]
        assert ts_list == sorted(ts_list)

    def test_non_complete_tasks_excluded_from_throughput(self):
        now = datetime.now(timezone.utc)
        rows = [
            _make_insight_row(status="error",      updated_at=now - timedelta(minutes=1)),
            _make_insight_row(status="processing", updated_at=now - timedelta(minutes=1), insight_type="graph"),
            _make_insight_row(status="pending",    updated_at=now - timedelta(minutes=1), insight_type="stats"),
        ]
        result, _ = self._call_handler(insight_rows=rows)
        assert result["throughput"]["5m"] == 0


# ── Timing computation helpers ────────────────────────────────────────────────

class TestTimingMath:

    def test_avg_of_empty_list_is_none(self):
        """_avg should return None for empty list, not divide by zero."""
        def _avg(lst):
            return round(sum(lst) / len(lst)) if lst else None
        assert _avg([]) is None

    def test_avg_rounds_correctly(self):
        def _avg(lst):
            return round(sum(lst) / len(lst)) if lst else None
        assert _avg([1000, 2000, 3000]) == 2000
        assert _avg([999]) == 999

    def test_queue_time_always_non_negative(self):
        """Queue time = started_at - generated_at; must not be negative."""
        now = datetime.now(timezone.utc)
        generated = now - timedelta(seconds=10)
        started   = now - timedelta(seconds=5)
        queue_ms = int((started - generated).total_seconds() * 1000)
        assert queue_ms >= 0

    def test_exec_time_always_non_negative(self):
        now = datetime.now(timezone.utc)
        started = now - timedelta(seconds=20)
        updated = now - timedelta(seconds=2)
        exec_ms = int((updated - started).total_seconds() * 1000)
        assert exec_ms >= 0
