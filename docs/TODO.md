# TODO — Dynamic File Upload (Phase 1)

Tracking the implementation of `implementation_dynamic_upload_files.md`.
Phase 1 scope: csv / tsv / jsonl / json / xlsx / txt / md handlers + storage +
pipeline + tasks + API + wizard step (drag-drop, multi-file) + detail-page
Uploads tab.

## In Progress
_(none)_

## Pending
_(none — Phase 1 + Phase 2 + tests + vLLM swap + live stats all complete)_

## Done
- [x] Brainstorm + plan: `implementation_dynamic_upload_files.md`
- [x] Example fixtures: `data/upload_examples/{csv,txt,jsonl,misc}/*`
- [x] Tracker: `docs/TODO.md`
- [x] Tests: 41 unit + 4 integration green (`tests/unit/test_ingestion_*.py`,
      `tests/integration/test_ingestion_pipeline.py`); 205/205 total
- [x] Tests: E2E suite written (`tests/e2e/test_uploads_flow.py`); auto-skips
      until backend is up
- [x] LLM: switch SGLang → vLLM in a standalone `docker-compose-llm.yml` so
      it can run on a separate GPU host; main compose no longer includes a
      GPU service. Updated `.env`, `Makefile`, and `CLAUDE.md`.
- [x] LLM stats compatibility under vLLM: `get_model_info()` now derives
      Architecture/Quantization/dtype/KV-Cache/VRAM from `cache_config_info`
      + model name; cached-404 prevents repeated noise.
- [x] Live LLM stats card on /overview: requests running/waiting, KV cache
      utilisation, prefix-cache hit rate, lifetime token counters,
      VRAM-per-request (theoretical + live modes; bytes-per-token derived
      from the model's HF `config.json`).
- [x] Phase 2 ingestion handlers: PDF (pypdf, page/paragraph chunking),
      DOCX (python-docx, paragraph/section + heading-as-title), HTML
      (BeautifulSoup, article/paragraph + canonical URL). Wired into the
      registry; 12 new unit tests + new fixtures
      (`docx_pdf/sample_brief.docx`, `docx_pdf/sample_intel.pdf`,
      `html/sample_report.html`).
- [x] Uniform DataTable rows: synthetic title fallback in normalizer
      (first ~80 chars of text, else `filename #N`); flagged via
      `title_synthetic` so the UI can dim them later if desired.
- [x] Add config + requirements (`UPLOADS_DIR`, `UPLOADS_MAX_SIZE_BYTES`,
      `INGEST_*`; deps `charset-normalizer`, `openpyxl`)
- [x] `src/ingestion/storage.py` — Storage protocol + LocalDiskStorage
      (streaming write, sha256 in single pass, size cap)
- [x] `src/ingestion/models.py` — UploadedFile, ParserProfile (wired into
      `core/db.py:init_db`)
- [x] `src/ingestion/handlers/base.py` — RawRecord + FileHandler protocol
- [x] `src/ingestion/handlers/__init__.py` — registry + `get_for()` dispatch
- [x] `src/ingestion/handlers/csv_handler.py` — auto delimiter+encoding,
      streaming row iterator, sorted-headers fingerprint
- [x] `src/ingestion/handlers/json_handler.py` — jsonl + json (top-level
      array streaming via brace-balanced parse for large files)
- [x] `src/ingestion/handlers/xlsx_handler.py` — openpyxl `read_only=True`
- [x] `src/ingestion/handlers/text_handler.py` — Telegram/Apache/syslog
      pattern inference + paragraph/line fallback
- [x] `src/ingestion/sniffer.py` — facade + accepted-formats listing
- [x] `src/ingestion/normalizer.py` — RawRecord → ES doc + stable_doc_id
- [x] `src/ingestion/profiles.py` — fingerprint lookup/upsert + mark_used
- [x] `src/ingestion/llm_mapping.py` — single LLM call + heuristic fallback
- [x] `src/ingestion/pipeline.py` — state machine
      `pending → parsing → mapping_review → indexing → complete | error`
- [x] `src/ingestion/tasks.py` — `@register("ingest_file")`,
      `@register("ingest_continue")`
- [x] `src/ingestion/service.py` — CRUD + lifecycle (incl.
      `DuplicateUploadError`)
- [x] API endpoints (8 routes) + `maps/endpoint.json` wiring
- [x] Frontend types: `UploadedFile`, `ProposedMapping`, `ParserProfile`,
      `AcceptedFormats`
- [x] `frontend/src/api/uploads.ts` — multipart streaming upload + CRUD
- [x] `frontend/src/hooks/useUploads.ts` — React Query hooks (poll while
      non-terminal)
- [x] `UploadFilesStep.tsx` — wizard drag-drop, multi-file, accepted
      formats list
- [x] `MappingReviewDrawer.tsx` — confirm proposed mapping; save-as-profile
- [x] `UploadsTab.tsx` — drag-drop + table on the investigation detail page
- [x] `CreateInvestigationWizard.tsx` — new step inserted between Scrapers
      and Enrichment; sequential file upload after creation
- [x] `InvestigationDetail.tsx` — Uploads tab added
- [x] Wired `tasking.handlers.dispatch_task` to consult the registry as a
      fallback (so `@register()` modules plug in without editing dispatch)
- [x] `mark_task_error` extended for `ingest_file` / `ingest_continue`
- [x] Investigation deletion now also purges the uploads tree
- [x] `_recover_dangling_tasks` republishes stuck uploads
- [x] `main.py` eager-imports `src.ingestion.tasks` at startup
- [x] Frontend `tsc --noEmit` clean

## Deferred (Phase 3+)
- eml, mbox, archive (zip/tar.gz) handlers
- OCR for scanned PDFs (tesseract pipeline)
- Audio/video transcription (Whisper)
- Incremental embedding (`embed_docs` is currently all-or-nothing per index)
- S3Storage backend
- PII auto-redaction before LLM calls
- Multi-sheet xlsx ingestion (currently first sheet only)
