"""User-uploaded file ingestion: arbitrary files → records → ES docs.

The ingestion pipeline turns user-uploaded files of varying formats
(csv, json, xlsx, txt, ...) into the same ES document shape that
scraped/searched documents already use, so search/retrieval/embedding/
enrichment/insights work over them uniformly.

See ``implementation_dynamic_upload_files.md`` for the full design.
"""
