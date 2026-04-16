"""Enrichment domain ORM model — DocumentEnrichment."""
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, Text, DateTime, JSON

from src.core.db import Base


class DocumentEnrichment(Base):
    __tablename__ = "rag_document_enrichment"

    doc_id     = Column(String(255), primary_key=True)
    datasource = Column(String(100), primary_key=True)

    status  = Column(String(20), nullable=False, default="pending", index=True)
    payload = Column(JSON,       nullable=True)
    error   = Column(Text,       nullable=True)

    generated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    started_at   = Column(DateTime, nullable=True)
    updated_at   = Column(DateTime, nullable=False,
                          default=lambda: datetime.now(timezone.utc),
                          onupdate=lambda: datetime.now(timezone.utc))

    retry_count  = Column(Integer, nullable=False, default=0)

    def to_dict(self):
        return {
            "doc_id":       self.doc_id,
            "datasource":   self.datasource,
            "status":       self.status,
            "payload":      self.payload,
            "error":        self.error,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "started_at":   self.started_at.isoformat()   if self.started_at   else None,
            "updated_at":   self.updated_at.isoformat()   if self.updated_at   else None,
            "retry_count":  self.retry_count,
        }
