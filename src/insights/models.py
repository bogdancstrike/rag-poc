"""Insights domain ORM model — InsightsCache."""
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, Text, DateTime, JSON, Index

from src.core.db import Base


class InsightsCache(Base):
    __tablename__ = "rag_insights_cache"

    datasource   = Column(String(100), primary_key=True, default="default")
    insight_type = Column(String(50),  primary_key=True)

    status       = Column(String(20),  nullable=False, default="pending", index=True)
    payload      = Column(JSON,        nullable=True)
    error        = Column(Text,        nullable=True)

    generated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    started_at   = Column(DateTime, nullable=True)
    updated_at   = Column(DateTime, nullable=False,
                          default=lambda: datetime.now(timezone.utc),
                          onupdate=lambda: datetime.now(timezone.utc))

    retry_count  = Column(Integer,  nullable=False, default=0)
    sample_hash  = Column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_insights_datasource_type", "datasource", "insight_type"),
    )

    def to_dict(self):
        return {
            "datasource":   self.datasource,
            "insight_type": self.insight_type,
            "status":       self.status,
            "payload":      self.payload,
            "error":        self.error,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "started_at":   self.started_at.isoformat()   if self.started_at   else None,
            "updated_at":   self.updated_at.isoformat()   if self.updated_at   else None,
            "retry_count":  self.retry_count,
            "sample_hash":  self.sample_hash,
        }
