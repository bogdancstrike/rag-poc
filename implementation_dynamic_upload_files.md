# Dynamic File Upload — Implementation Plan

Add the ability to ingest arbitrary user-supplied files (CSV, JSON/JSONL, XLSX,
TXT, MD, DOCX, PDF, HTML, EML/MBOX, archives) into an investigation's ES index,
so they participate in search, retrieval, embedding, enrichment and insights
identically to scraped/searched documents.

This document is the contract between brainstorm and implementation. Once
agreed, the actual code follows the layout in §4.

---

## 1. Scope

### Goals
- One uniform pipeline: **file → records → normalized ES docs → existing
  retrieval/embedding/enrichment paths**. We do NOT add a parallel search
  stack; we add a new *source*.
- Streaming: files of multi-GB size must not load fully into memory.
- Auto + confirm: for tabular files, the LLM proposes a column→field mapping;
  the user confirms (or edits) before ingestion runs.
- **Parser-profile reuse:** when a structurally identical file is uploaded
  again (e.g. `leak_2024.csv` → `leak_2025.csv`), reuse the saved mapping
  without re-asking the LLM or the user.
- Original files are kept on disk for audit/replay.
- Reachable from both the create-investigation wizard *and* the investigation
  detail page (an "Uploads" tab).

### Non-goals (Phase 1)
- OCR for scanned PDFs (defer — needs tesseract).
- Audio/video transcription.
- Cross-investigation file sharing.
- Resumable / chunked uploads (tus, multipart resume) — single-shot streaming
  upload only. Acceptable for files up to a few GB on a LAN; revisit later.
- Auto-redaction of PII before LLM calls. (Local SGLang/Ollama means content
  doesn't leave the machine; this is a future hardening step.)

---

## 2. User flows

### A. Wizard (CreateInvestigationWizard.tsx)
Insert a new step **Upload Files** between *Scrapers* (step 2) and *Enrichment*
(step 3). Resulting step order:

```
0 Name → 1 Searches → 2 Scrapers (mock) → 3 Upload Files → 4 Enrichment → 5 Review
```

In the wizard, files are *staged* in browser state (a list of `File` objects
plus, for each, a tentative parser-profile choice or "auto-detect"). Actual
upload happens immediately *after* `create_investigation` returns 202: the
frontend POSTs each file to `/rag/v1/investigations/{id}/uploads` in sequence.
The wizard closes; progress is observed on the detail page.

### B. Investigation detail page
A new **Uploads** tab containing:
- Drag-and-drop area for new files.
- Table of past uploads: filename, size, status (`pending` →
  `parsing` → `mapping_review` → `indexing` → `complete` / `error`),
  doc count, source profile, actions (retry, delete index entries, download
  original).
- For files in `mapping_review`, a side panel shows the LLM-proposed mapping
  (CSV columns → `text/title/created_at/author/url/raw`) with a sample of the
  first 5 records, plus a save-as-profile checkbox.

### C. Re-upload of structurally identical file
1. User uploads `leak_2025.csv`.
2. Sniffer + handler reads first chunk, computes structure fingerprint.
3. `parser_profile_service.find_by_fingerprint(fingerprint)` returns the
   profile saved from `leak_2024.csv` (mapping + parsing options).
4. Status skips `mapping_review` and goes directly to `indexing`. Profile
   `usage_count++`, `last_used_at = now`.

---

## 3. Data model

### 3.1 New tables (Postgres, via SQLAlchemy in `src/ingestion/models.py`)

```sql
CREATE TABLE rag_uploaded_files (
    id                UUID PRIMARY KEY,
    investigation_id  UUID REFERENCES rag_investigations(id) ON DELETE CASCADE,
    filename          TEXT NOT NULL,
    storage_uri       TEXT NOT NULL,           -- e.g. file:///data/uploads/<inv>/<id>/<name>
    size_bytes        BIGINT NOT NULL,
    sha256            CHAR(64) NOT NULL,        -- of the file content
    mime_type         TEXT,
    handler_name      TEXT,                     -- e.g. "csv", "jsonl", "pdf"
    profile_id        UUID NULL REFERENCES rag_parser_profiles(id),
    status            TEXT NOT NULL,            -- pending|parsing|mapping_review|indexing|complete|error
    error             TEXT NULL,
    record_count      INTEGER NULL,             -- records produced
    indexed_count     INTEGER NULL,             -- successfully indexed into ES
    proposed_mapping  JSONB NULL,               -- LLM's suggested mapping awaiting user confirmation
    final_mapping     JSONB NULL,               -- mapping actually used at ingestion time
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (investigation_id, sha256)           -- idempotent re-upload of identical file
);
CREATE INDEX ON rag_uploaded_files (investigation_id, status);

CREATE TABLE rag_parser_profiles (
    id              UUID PRIMARY KEY,
    handler_name    TEXT NOT NULL,
    fingerprint     CHAR(64) NOT NULL,          -- sha256 of canonical structure description
    name            TEXT NULL,                   -- optional human label, settable later
    mapping         JSONB NOT NULL,              -- column/field → normalized field
    options         JSONB NOT NULL DEFAULT '{}', -- delimiter, encoding, header_row, etc.
    sample          JSONB NULL,                  -- the first 3 sample records, for UI preview
    usage_count     INTEGER NOT NULL DEFAULT 0,
    last_used_at    TIMESTAMPTZ NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (handler_name, fingerprint)
);
```

### 3.2 ES doc shape (already implicit; we make it explicit)
Every ingested record produces a doc indexed into the investigation index:

```json
{
  "text":        "primary searchable text",
  "title":       "optional",
  "created_at":  "ISO8601 or null",
  "author":      "optional",
  "url":         "optional",
  "source":      "upload:<file_id>#<record_index>",
  "raw":         { ...original record verbatim... },
  "embedding":   [...]    // populated later by handle_embed_docs
}
```

The `source` field is the new contract. It lets the UI filter "show me what
came from leak.csv" without changing existing search code.

### 3.3 Fingerprint derivation
Per handler, `fingerprint(handler_inputs) → sha256_hex`:

| Handler  | Fingerprint input                                                      |
|----------|------------------------------------------------------------------------|
| csv/tsv  | `sha256("\t".join(sorted(lower(strip(headers)))) + "\n" + delimiter)`  |
| jsonl    | `sha256("\n".join(sorted(union of top-level keys from first 100 rows)))` |
| json     | same as jsonl when the root is an array; else "single-doc"             |
| xlsx     | per sheet: same as csv, joined with sheet names                        |
| docx     | content-shape-agnostic: `"docx"` (no useful structural reuse)          |
| pdf      | `"pdf"` (same)                                                         |
| txt      | derived from a first-pass *line classifier* (see §6.5); profile may
            reuse if the same regex pattern matches                                  |

Profiles for `docx`/`pdf` exist primarily to record per-file choices
(language, paragraph vs. page chunking) — not for cross-file reuse.

---

## 4. Module layout

Following the existing modulith pattern (`src/<domain>/{models,service,...}.py`):

```
src/ingestion/
├── __init__.py
├── models.py                  # UploadedFile, ParserProfile ORM
├── service.py                 # CRUD, lifecycle transitions
├── storage.py                 # Storage protocol + LocalDiskStorage
├── sniffer.py                 # content-based format detection (extension is unreliable)
├── normalizer.py              # RawRecord -> ES doc
├── pipeline.py                # streaming orchestrator: handler -> normalize -> bulk index
├── profiles.py                # fingerprint computation + profile lookup/upsert
├── llm_mapping.py             # LLM-driven column/field mapping inference (1 call/file)
├── tasks.py                   # @register("ingest_file") + helpers; imported on startup
└── handlers/
    ├── __init__.py            # registry: register(handler), get_for(path)
    ├── base.py                # FileHandler protocol + RawRecord dataclass
    ├── csv_handler.py         # csv, tsv
    ├── json_handler.py        # json, jsonl
    ├── xlsx_handler.py        # xlsx
    ├── text_handler.py        # txt, md, log (with line-pattern inference)
    ├── docx_handler.py        # docx
    ├── pdf_handler.py         # pdf (text-extract only; OCR deferred)
    ├── html_handler.py        # html
    ├── email_handler.py       # eml, mbox
    └── archive_handler.py     # zip, tar.gz — recurses into other handlers
```

### Public surface (what other modules call)
- `ingestion.service.create_upload(investigation_id, filename, stream) -> dict`
- `ingestion.service.get_upload(file_id) -> dict | None`
- `ingestion.service.list_uploads(investigation_id) -> list[dict]`
- `ingestion.service.confirm_mapping(file_id, final_mapping, save_as_profile: bool, profile_name: str|None) -> dict`
- `ingestion.service.delete_upload(file_id, purge_es: bool) -> bool`

The wizard / detail page never touches handlers directly — they go through
`service`. Handlers are registered at import time and discovered by
`handlers.__init__.get_for(path, mime)`.

---

## 5. Storage interface

```python
class Storage(Protocol):
    def write(self, key: str, stream: BinaryIO) -> str:
        """Persist `stream` under `key`. Return absolute URI (e.g. file:///...)."""
    def open(self, key_or_uri: str) -> BinaryIO:
        """Open a stored object for streaming reads."""
    def delete(self, key_or_uri: str) -> None: ...
    def size(self, key_or_uri: str) -> int: ...
```

Phase-1 implementation: `LocalDiskStorage(root=Config.UPLOADS_DIR)`. Layout
on disk:

```
${UPLOADS_DIR}/
  <investigation_id>/
    <file_id>/
      original.<ext>          # exact bytes the user uploaded
      meta.json               # filename, size, sha256, mime, uploaded_at
```

Future: `S3Storage` implementing the same protocol; switch via env.

---

## 6. Handler design

### 6.1 `RawRecord` dataclass (`handlers/base.py`)

```python
@dataclass(slots=True)
class RawRecord:
    text: str                              # required
    title:      Optional[str] = None
    created_at: Optional[str] = None       # ISO8601
    author:     Optional[str] = None
    url:        Optional[str] = None
    raw:        dict = field(default_factory=dict)
    record_index: int = 0                  # ordinal within file (for stable _id)
```

### 6.2 `FileHandler` protocol

```python
class FileHandler(Protocol):
    name: str                              # "csv", "pdf", ...
    extensions: tuple[str, ...]
    mime_types: tuple[str, ...]

    def sniff(self, head: bytes) -> float:
        """Confidence in [0,1] that this handler should parse the file."""

    def fingerprint(self, path: Path, options: dict) -> str | None:
        """Stable structural hash, or None if structure-reuse is not meaningful."""

    def propose_mapping(self, path: Path, options: dict) -> dict:
        """Sample first N records; return {'columns': [...], 'samples': [...],
           'suggested_mapping': {...}}. May call the LLM."""

    def extract(self, path: Path, mapping: dict, options: dict) -> Iterator[RawRecord]:
        """Stream records lazily. Caller batches into bulk-index calls."""

    def estimate_records(self, path: Path, options: dict) -> int | None:
        """Best-effort total — for progress UI. None if unknown."""
```

### 6.3 Mapping shape (per format family)

**Tabular (csv/tsv/jsonl/xlsx):**
```json
{
  "text":       "body",          // required — column to use as primary text
  "title":      "subject",        // optional
  "created_at": "timestamp",      // optional
  "author":     "user_name",      // optional
  "url":        null,
  "concat_text_columns": []       // optional fallback: concatenate these into text
}
```

**Document (pdf/docx/html):**
```json
{
  "chunking":  "page" | "paragraph" | "heading",
  "language":  "auto" | "ro" | "en" | ...,
  "title":     "auto" | "<filename>"
}
```

**Text (txt/md/log):**
```json
{
  "mode":          "line" | "paragraph" | "regex",
  "regex":         "^\\[(?P<created_at>[^\\]]+)\\]\\s+(?P<author>\\w+):\\s+(?P<text>.*)$",
  "min_chars":     20,
  "drop_empty":    true
}
```

### 6.4 LLM mapping inference (`llm_mapping.py`)
Called once per file when no profile matches. Inputs: handler name, column
names (or sample structure), 5 sample records. Output JSON:

```json
{
  "mapping": { "text": "body", "title": "subject", ... },
  "confidence": 0.92,
  "rationale": "column 'body' is the longest free-text field; 'subject' looks like a title"
}
```

Re-uses `LLMClient.complete_json()` (same retry-with-higher-temp pattern as
`enrichment.pipeline`). One call per file. Total cost: trivial.

### 6.5 Text handler — pattern inference
For `.txt`/`.log`, `propose_mapping` runs a small heuristic line classifier:
- If >70% of the first 200 non-empty lines match a known pattern (Apache log,
  Telegram chat, syslog, generic `[timestamp] author: text`), return that
  regex with `mode="regex"`.
- Otherwise default to `mode="paragraph"` (split on blank lines).
- The user can override either in the wizard.

### 6.6 Archive handler
Streams entries via `zipfile.ZipFile.open(name)` (no full extraction).
Recurses into the registered handlers per inner file. Hard caps:
- `MAX_ARCHIVE_DEPTH=2`
- `MAX_ARCHIVE_TOTAL_BYTES=5 * file_size` (anti-zip-bomb)
- Skips entries with absolute paths or `..` components.

---

## 7. Ingestion pipeline (`pipeline.py`)

State machine (one row per file in `rag_uploaded_files`):

```
pending          ← row created at upload-receive time
   ↓ (handle_ingest_file picks up; sniff + handler)
parsing          ← reading head, computing fingerprint, propose_mapping
   ↓ profile hit:                       ↓ profile miss:
                                  mapping_review ← UI shows proposed mapping
                                        ↓ user confirms via API
indexing         ← stream extract → batch normalize → es.bulk_index
   ↓
complete         ← record_count, indexed_count populated
                   then publish_task("embed_docs") and (optional)
                   the same auto-enrichment fan-out used by searches
```

Failure paths set `status=error` with `error` populated. Each transition is
logged with the same `[ingest]` prefix style used elsewhere
(`[insight]`, `[enrich]`).

### 7.1 Streaming + batching
Pseudo-code for the hot loop:

```python
batch: list[dict] = []
for record in handler.extract(path, mapping, options):
    es_doc = normalizer.normalize(record, file_id, source_label)
    batch.append({"_id": _stable_id(file_id, record.record_index), **es_doc})
    if len(batch) >= Config.INGEST_BATCH_SIZE:   # default 500
        es.bulk_index(index_name, batch); batch.clear()
        upload.indexed_count += done; commit()
if batch:
    es.bulk_index(index_name, batch)
```

`_stable_id = sha256(file_id + ':' + record_index)` — re-running ingestion
is idempotent; partial failures resume cleanly because ES upserts on `_id`.

### 7.2 Cross-investigation re-upload (idempotency)
The `(investigation_id, sha256)` unique constraint catches the trivial case:
exact same bytes uploaded twice → 409 with the existing `file_id`.

---

## 8. Task system integration

Two new task types, registered via `tasking.registry`:

| Task                  | Topic        | Reason                                          |
|-----------------------|--------------|-------------------------------------------------|
| `ingest_file`         | `fast_tasks` | I/O bound; LLM mapping is one call (negligible) |
| `ingest_continue`     | `fast_tasks` | Resumes a file after user confirms mapping      |

`ingest_continue` is published from the `confirm_mapping` API after the
user clicks "Confirm" in the UI — the work itself is the same as the second
half of `ingest_file`.

`embed_docs` and `enrich_doc` already exist; we publish them at the end of
`ingest_continue` to match what `handle_create_investigation` already does
after the search-based seeding.

### Recovery
Add upload status to `_recover_dangling_tasks` in `main.py`:
- `parsing` / `indexing` rows → republish `ingest_file` or `ingest_continue`
  depending on which stage they were in. The original file is on disk, so
  re-running is safe.

---

## 9. API endpoints (added to `maps/endpoint.json` + `api/endpoints.py`)

| Method | Path                                                          | Purpose                                  |
|--------|---------------------------------------------------------------|------------------------------------------|
| POST   | `/v1/investigations/<investigation_id>/uploads`               | Multipart upload; returns 202 + file row |
| GET    | `/v1/investigations/<investigation_id>/uploads`               | List uploads                             |
| GET    | `/v1/uploads/<file_id>`                                       | Detail (incl. proposed_mapping)          |
| POST   | `/v1/uploads/<file_id>/confirm`                               | Body `{mapping, save_as_profile, name?}` |
| DELETE | `/v1/uploads/<file_id>`                                       | Optional `?purge_es=true` to delete docs |
| GET    | `/v1/uploads/<file_id>/download`                              | Stream original file back                |
| GET    | `/v1/parser-profiles`                                         | List (for "use existing profile" UX)     |
| DELETE | `/v1/parser-profiles/<id>`                                    | Remove                                   |

The upload POST uses `flask.request.stream` directly so multi-GB requests
don't buffer in memory. The handler writes to `Storage.write()` while
computing sha256 + size, then enqueues `ingest_file`.

---

## 10. Frontend

### 10.1 Wizard
Add `UploadFilesStep` component after the scrapers step. Pure browser-side
staging — files held in component state until the wizard's `handleCreate`
finishes. After `createInv.mutate` resolves, iterate the staged files and
POST each to `/v1/investigations/{id}/uploads`. No mapping UI in the wizard:
files default to "auto-detect" and any tabular file lands in
`mapping_review`, surfaced on the detail page.

### 10.2 Detail page (`InvestigationDetail.tsx`)
New tab `Uploads`:
- `UploadsTable` — paginates `useUploads(investigationId)`.
- `UploadDropzone` — drag-and-drop, multi-file.
- `MappingReviewDrawer` — opens for files in `mapping_review`. Shows column
  list, sample rows, the LLM's suggested mapping, save-as-profile toggle.
  POSTs `/v1/uploads/{id}/confirm` on submit.
- `useUploads` / `useConfirmMapping` React Query hooks.

### 10.3 Status surfacing
Extend the existing investigation status union (`creating | ready |
ready_with_vectors | error`) with **no change** — uploads have their own
status field. The investigation card stays clean; the badge "N uploads in
progress" lives only on the detail page.

---

## 11. Configuration (env additions)

```bash
# Storage
UPLOADS_DIR=./data/uploads
UPLOADS_MAX_SIZE_BYTES=5368709120          # 5 GB; 0 = unlimited

# Pipeline
INGEST_BATCH_SIZE=500
INGEST_TEXT_TRUNCATE=20000                  # cap per record before indexing
INGEST_SAMPLE_RECORDS=5                     # sent to LLM for mapping inference

# Handlers
INGEST_PDF_MAX_PAGES=2000
INGEST_ARCHIVE_MAX_DEPTH=2
INGEST_ARCHIVE_EXPANSION_RATIO=20           # max expanded:compressed ratio
```

All readable from `Config` class as class-level attrs (matches existing style).

---

## 12. Limitations / known sharp edges

1. **Encoding** — `chardet`/`charset-normalizer` covers most leaks; rare
   ones (mixed encodings within one file) will produce mojibake in `raw`.
2. **PDFs** — text-only extraction. Scanned PDFs ingest as empty/garbage
   text; surfaced as a warning on the upload row.
3. **Embedding cost** — embedding 1M docs at fastembed CPU rate (~50/s)
   is ~5.5 hours. We don't block ingestion on it; `embed_docs` runs in the
   background and the UI shows `ready` (BM25-only) until vectors are ready.
4. **Auto-enrichment** — same `autoEnrichCount` that searches use. For a
   100k-row leak the user almost certainly wants this off; default is
   inherited from the wizard, but the detail-page Uploads tab gets its own
   "enrich first N" override.
5. **Re-embedding after upload** — current `handle_embed_docs` is
   all-or-nothing per index. Until we add an incremental path, an upload
   after embedding has run will trigger a full re-embed. Acceptable for
   Phase 1; tracked as a follow-up.
6. **Profile fingerprint collisions** — vanishingly rare for CSV (full
   header set) but possible for `txt` regex patterns. Profile carries a
   sample so the user can see the wrong-fit and override.
7. **Concurrent uploads** — `handle_ingest_file` runs in `fast_tasks` which
   uses an unbounded thread pool. Two large uploads = two streaming reads;
   ES bulk-index throughput becomes the bottleneck before disk does.
8. **Restart mid-indexing** — recovery republishes `ingest_continue` and
   ES upserts on `_id` make this idempotent. A small window of duplicate
   work (re-indexing already-indexed records) is accepted.

---

## 13. Phasing

| Phase | Handlers                            | Notes                              |
|-------|-------------------------------------|------------------------------------|
| 1     | csv, tsv, jsonl, json, xlsx, txt    | Core. Covers ~80% of "USB grab-bag"|
| 2     | pdf, docx, html                     | Doc-style content                  |
| 3     | eml, mbox, archives                 | Email leaks, multi-file dumps      |
| 4     | (deferred) ocr, audio               | Heavy; needs separate planning     |

Phase 1 is the contract for the first PR. Phases 2 and 3 are pure additions
under `handlers/` — no API or pipeline changes.

---

## 14. Test surface

- Unit: each handler against the example fixtures in `data/upload_examples/`.
- Unit: `profiles.fingerprint()` is stable across re-reads of the same file.
- Unit: `pipeline.normalize()` produces a doc that round-trips through
  `ESClient.bulk_index` and is then retrievable via `Retriever`.
- Integration: upload `leak_users_2024.csv`, confirm mapping, save profile;
  upload `leak_users_2025.csv` → assert profile matched and no LLM call was
  made (`mock_llm_client.assert_not_called()`).
- Integration: upload a 100k-row CSV → assert peak RSS stays under 500MB
  (proves streaming).

---

## 15. Open questions (small, can defer)

- Should `confirm_mapping` allow editing parser **options** (delimiter,
  encoding) too, or only the column→field mapping? Recommend: yes, editable
  in an "advanced" disclosure.
- For files > some threshold, do we want to compute the fingerprint
  *during* the upload write rather than after? Recommend: no — the head
  is small, so a second open-and-read is cheap and keeps upload simple.
- "Same investigation, two CSVs with the same fingerprint, conflicting
  mapping overrides" — recommend: per-file `final_mapping` always wins;
  the profile is just a default.
