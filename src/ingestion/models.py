"""Ingestion ORM models — uploaded files and reusable parser profiles."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Text, DateTime, JSON, BigInteger,
    ForeignKey, UniqueConstraint, Index,
)

from src.core.db import Base


# ── Status values for UploadedFile.status ─────────────────────────────────────
# pending          row exists, file written to disk, ingest task queued
# parsing          handler picked, computing fingerprint / sample
# mapping_review   awaiting user confirmation of LLM-proposed column mapping
# indexing         streaming records into the investigation's ES index
# complete         all records indexed; embed_docs may still be running
# error            terminal failure; ``error`` column populated
UPLOAD_STATUSES = (
    "pending", "parsing", "mapping_review", "indexing", "complete", "error",
)


class UploadedFile(Base):
    """One row per uploaded file. Lifecycle is the state machine in
    ``ingestion.pipeline``; the original bytes live on disk via
    ``ingestion.storage`` and are never duplicated into the DB."""
    __tablename__ = "rag_uploaded_files"

    id               = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    investigation_id = Column(String(36),
                              ForeignKey("rag_investigations.id", ondelete="CASCADE"),
                              nullable=False, index=True)
    filename         = Column(Text, nullable=False)
    storage_uri      = Column(Text, nullable=False)        # e.g. file:///abs/path
    size_bytes       = Column(BigInteger, nullable=False)
    sha256           = Column(String(64), nullable=False)
    mime_type        = Column(Text, nullable=True)
    handler_name     = Column(String(40), nullable=True)   # "csv", "jsonl", etc.
    profile_id       = Column(String(36),
                              ForeignKey("rag_parser_profiles.id", ondelete="SET NULL"),
                              nullable=True)
    status           = Column(String(20), nullable=False, default="pending", index=True)
    error            = Column(Text, nullable=True)
    record_count     = Column(Integer, nullable=True)      # records produced by extract()
    indexed_count    = Column(Integer, nullable=True)      # records actually bulk-indexed
    proposed_mapping = Column(JSON, nullable=True)         # LLM proposal awaiting confirm
    final_mapping    = Column(JSON, nullable=True)         # mapping actually used
    options          = Column(JSON, nullable=False, default=dict)  # delimiter, encoding, ...
    created_at       = Column(DateTime, nullable=False,
                              default=lambda: datetime.now(timezone.utc))
    updated_at       = Column(DateTime, nullable=False,
                              default=lambda: datetime.now(timezone.utc),
                              onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        # Re-uploading the exact same bytes into the same investigation is a
        # no-op: the existing row is returned via 409 by the API.
        UniqueConstraint("investigation_id", "sha256", name="uq_upload_inv_sha256"),
    )

    def to_dict(self) -> dict:
        return {
            "id":               self.id,
            "investigation_id": self.investigation_id,
            "filename":         self.filename,
            "storage_uri":      self.storage_uri,
            "size_bytes":       self.size_bytes,
            "sha256":           self.sha256,
            "mime_type":        self.mime_type,
            "handler_name":     self.handler_name,
            "profile_id":       self.profile_id,
            "status":           self.status,
            "error":            self.error,
            "record_count":     self.record_count,
            "indexed_count":    self.indexed_count,
            "proposed_mapping": self.proposed_mapping,
            "final_mapping":    self.final_mapping,
            "options":          self.options or {},
            "created_at":       self.created_at.isoformat() if self.created_at else None,
            "updated_at":       self.updated_at.isoformat() if self.updated_at else None,
        }


class ParserProfile(Base):
    """Cached column→field mapping keyed by structural fingerprint.

    When an upload's structure (e.g. set of CSV headers) matches an existing
    profile, we reuse its ``mapping`` and ``options`` instead of asking the
    LLM again or prompting the user. Profiles are global (not scoped to an
    investigation) — same shape, same mapping, regardless of where it lands.
    """
    __tablename__ = "rag_parser_profiles"

    id           = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    handler_name = Column(String(40), nullable=False)         # "csv", "jsonl", ...
    fingerprint  = Column(String(64), nullable=False)         # sha256 hex of structure
    name         = Column(Text, nullable=True)                # optional human label
    mapping      = Column(JSON, nullable=False)
    options      = Column(JSON, nullable=False, default=dict) # delimiter, encoding, ...
    sample       = Column(JSON, nullable=True)                # first few records (for UI preview)
    usage_count  = Column(Integer, nullable=False, default=0)
    last_used_at = Column(DateTime, nullable=True)
    created_at   = Column(DateTime, nullable=False,
                          default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("handler_name", "fingerprint", name="uq_profile_handler_fp"),
        Index("ix_profile_fp", "fingerprint"),
    )

    def to_dict(self) -> dict:
        return {
            "id":           self.id,
            "handler_name": self.handler_name,
            "fingerprint":  self.fingerprint,
            "name":         self.name,
            "mapping":      self.mapping,
            "options":      self.options or {},
            "sample":       self.sample,
            "usage_count":  self.usage_count,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "created_at":   self.created_at.isoformat() if self.created_at else None,
        }
