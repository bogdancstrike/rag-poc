# TODO — Dynamic File Upload (Phase 1)

Tracking the implementation of `implementation_dynamic_upload_files.md`.
Phase 1 scope: csv / tsv / jsonl / json / xlsx / txt / md handlers + storage +
pipeline + tasks + API + wizard step (drag-drop, multi-file) + detail-page
Uploads tab.

## In Progress
- [x] Create docs/TODO.md tracker

## Pending — Backend

- [ ] Add config + requirements
      `UPLOADS_DIR`, `UPLOADS_MAX_SIZE_BYTES`, `INGEST_BATCH_SIZE`,
      `INGEST_TEXT_TRUNCATE`, `INGEST_SAMPLE_RECORDS`,
      `INGEST_ARCHIVE_*` (parked for Phase 3 but reserved).
      `requirements.txt`: `openpyxl`, `charset-normalizer`.
- [ ] `src/ingestion/storage.py` — `Storage` protocol + `LocalDiskStorage`.
      Streaming write computes sha256 + size during write (single pass).
- [ ] `src/ingestion/models.py` — `UploadedFile`, `ParserProfile`. Wire into
      `src/core/db.py:init_db` so tables are created on startup.
- [ ] `src/ingestion/handlers/base.py` — `RawRecord` dataclass +
      `FileHandler` Protocol.
- [ ] `src/ingestion/handlers/__init__.py` — registry: `register()`,
      `get_for(path, mime, sniff_head)`, ordered by sniff confidence.
- [ ] `src/ingestion/handlers/csv_handler.py` — csv, tsv. Auto-detect
      delimiter + encoding. Streaming row iterator. Fingerprint = sorted
      lowercased headers + delimiter.
- [ ] `src/ingestion/handlers/json_handler.py` — json (top-level array) +
      jsonl. Streaming `ijson`-style parse for arrays.
- [ ] `src/ingestion/handlers/xlsx_handler.py` — openpyxl `read_only=True`
      streaming, per-sheet.
- [ ] `src/ingestion/handlers/text_handler.py` — txt, md, log. Pattern
      inference (Telegram/syslog/Apache/generic), paragraph fallback.
- [ ] `src/ingestion/sniffer.py` — content-based detection (extension
      unreliable for leak files).
- [ ] `src/ingestion/normalizer.py` — `RawRecord` → ES doc with the agreed
      schema (text/title/created_at/source/raw/...).
- [ ] `src/ingestion/profiles.py` — fingerprint compute + lookup/upsert.
- [ ] `src/ingestion/llm_mapping.py` — single LLM call per file; reuses
      `LLMClient.complete_json` retry pattern.
- [ ] `src/ingestion/pipeline.py` — state machine
      `pending → parsing → mapping_review → indexing → complete | error`.
      Streaming + batched bulk-index (default `INGEST_BATCH_SIZE=500`).
- [ ] `src/ingestion/tasks.py` — `@register("ingest_file")`,
      `@register("ingest_continue")`. Routed to `fast_tasks` topic.
- [ ] `src/ingestion/service.py` — `create_upload`, `get_upload`,
      `list_uploads`, `confirm_mapping`, `delete_upload`,
      `list_profiles`, `delete_profile`.
- [ ] API: `POST /v1/investigations/<id>/uploads`,
      `GET /v1/investigations/<id>/uploads`, `GET /v1/uploads/<id>`,
      `POST /v1/uploads/<id>/confirm`, `DELETE /v1/uploads/<id>`,
      `GET /v1/uploads/<id>/download`, `GET /v1/parser-profiles`,
      `DELETE /v1/parser-profiles/<id>`.
- [ ] `maps/endpoint.json` entries for the 8 routes above.
- [ ] `main.py` — import `src.ingestion.tasks` for handler registration;
      extend `_recover_dangling_tasks` for stuck uploads.

## Pending — Frontend

- [ ] `frontend/src/types/index.ts` — `UploadedFile`, `ParserProfile`,
      `MappingProposal`.
- [ ] `frontend/src/api/client.ts` — upload (multipart), list, detail,
      confirm, delete, download.
- [ ] `frontend/src/hooks/useUploads.ts` — React Query hooks.
- [ ] `frontend/src/components/investigations/UploadFilesStep.tsx` —
      wizard step with `Upload.Dragger` (multi-file drag-drop, antd).
- [ ] `frontend/src/components/investigations/CreateInvestigationWizard.tsx`
      — insert step between Scrapers and Enrichment; in `handleCreate`,
      after the investigation is created, POST staged files in sequence.
- [ ] `frontend/src/components/investigations/UploadsTab.tsx` — table,
      dropzone, status badges, retry/delete actions.
- [ ] `frontend/src/components/investigations/MappingReviewDrawer.tsx` —
      shows proposed mapping, sample rows, save-as-profile checkbox.
- [ ] `frontend/src/components/investigations/InvestigationDetail.tsx` —
      add `Uploads` tab.

## Pending — Wiring

- [ ] Import `src.ingestion.tasks` at app startup so handlers register
      with `tasking.registry`.
- [ ] Add `ingest_file` / `ingest_continue` to producer's
      `fast_tasks` routing list (default; no LLM lane needed —
      mapping-inference is one short call).
- [ ] Extend `_recover_dangling_tasks` to requeue uploads stuck in
      `parsing` / `indexing` (file is on disk, replay is idempotent).

## Pending — Tests

- [ ] `tests/unit/test_ingestion_handlers.py` — parse each fixture in
      `data/upload_examples/`; assert column detection.
- [ ] `tests/unit/test_ingestion_profiles.py` — `leak_users_2024.csv`
      and `leak_users_2025.csv` produce identical fingerprints.
- [ ] `tests/unit/test_ingestion_normalizer.py` — RawRecord round-trip.

## Done
- [x] Brainstorm + plan: `implementation_dynamic_upload_files.md`
- [x] Example fixtures: `data/upload_examples/{csv,txt,jsonl,misc}/*`
- [x] Tracker: `docs/TODO.md`

## Deferred (Phase 2+)
- pdf, docx, html handlers
- eml, mbox, archive handlers
- OCR for scanned PDFs
- Audio/video transcription
- Incremental embedding (`embed_docs` is currently all-or-nothing per index)
- S3Storage backend
- PII auto-redaction before LLM calls
