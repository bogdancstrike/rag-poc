"""Backward-compatibility shim — re-exports from new canonical module locations.

New code should import directly from:
  src.core.db          — Base, get_engine, get_session_factory, get_db, init_db
  src.chat.models      — Session, Message
  src.insights.models  — InsightsCache
  src.enrichment.models — DocumentEnrichment
  src.investigations.models — DocumentStatus, DocumentLabel, SavedSearch,
                               Investigation, InvestigationSearch
"""
from src.core.db import (  # noqa: F401
    Base, get_engine, get_session_factory, get_db, init_db,
)
from src.chat.models import Session, Message  # noqa: F401
from src.insights.models import InsightsCache  # noqa: F401
from src.enrichment.models import DocumentEnrichment  # noqa: F401
from src.investigations.models import (  # noqa: F401
    DocumentStatus, DocumentLabel,
    SavedSearch, Investigation, InvestigationSearch,
)
