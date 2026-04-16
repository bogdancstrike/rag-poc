"""Investigations domain ORM models."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, Text, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship

from src.core.db import Base


class DocumentStatus(Base):
    __tablename__ = "rag_document_status"

    doc_id     = Column(String(255), primary_key=True)
    datasource = Column(String(100), primary_key=True)
    status     = Column(String(20),  nullable=False)
    updated_at = Column(DateTime, nullable=False,
                        default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "doc_id":     self.doc_id,
            "datasource": self.datasource,
            "status":     self.status,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class DocumentLabel(Base):
    __tablename__ = "rag_document_labels"

    doc_id     = Column(String(255), primary_key=True)
    datasource = Column(String(100), primary_key=True)
    labels     = Column(JSON, nullable=False, default=list)
    updated_at = Column(DateTime, nullable=False,
                        default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "doc_id":     self.doc_id,
            "datasource": self.datasource,
            "labels":     self.labels or [],
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SavedSearch(Base):
    __tablename__ = "rag_saved_searches"

    id          = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name        = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    query       = Column(Text, nullable=False, default="")
    filters     = Column(JSON, nullable=False, default=dict)
    created_at  = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at  = Column(DateTime, nullable=False,
                         default=lambda: datetime.now(timezone.utc),
                         onupdate=lambda: datetime.now(timezone.utc))

    investigation_links = relationship("InvestigationSearch", back_populates="search",
                                       cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id":          self.id,
            "name":        self.name,
            "description": self.description,
            "query":       self.query,
            "filters":     self.filters or {},
            "created_at":  self.created_at.isoformat() if self.created_at else None,
            "updated_at":  self.updated_at.isoformat() if self.updated_at else None,
        }


class Investigation(Base):
    __tablename__ = "rag_investigations"

    id          = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name        = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    index_name  = Column(String(255), nullable=False)
    status      = Column(String(20),  nullable=False, default="creating", index=True)
    error_msg   = Column(Text, nullable=True)
    doc_count   = Column(Integer, nullable=True)
    created_at  = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at  = Column(DateTime, nullable=False,
                         default=lambda: datetime.now(timezone.utc),
                         onupdate=lambda: datetime.now(timezone.utc))

    search_links = relationship("InvestigationSearch", back_populates="investigation",
                                cascade="all, delete-orphan")

    def to_dict(self, search_ids: list[str] | None = None):
        return {
            "id":          self.id,
            "name":        self.name,
            "description": self.description,
            "index_name":  self.index_name,
            "status":      self.status,
            "error_msg":   self.error_msg,
            "doc_count":   self.doc_count,
            "search_ids":  search_ids if search_ids is not None else [],
            "created_at":  self.created_at.isoformat() if self.created_at else None,
            "updated_at":  self.updated_at.isoformat() if self.updated_at else None,
        }


class InvestigationSearch(Base):
    __tablename__ = "rag_investigation_searches"

    investigation_id = Column(String(36),
                              ForeignKey("rag_investigations.id", ondelete="CASCADE"),
                              primary_key=True)
    search_id        = Column(String(36),
                              ForeignKey("rag_saved_searches.id", ondelete="CASCADE"),
                              primary_key=True)

    investigation = relationship("Investigation", back_populates="search_links")
    search        = relationship("SavedSearch",   back_populates="investigation_links")
