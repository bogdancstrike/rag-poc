"""Backward-compatibility shim → src.insights.engine"""
from src.insights.engine import (  # noqa: F401
    InsightsEventBus, InsightsEngine, get_insights_engine, _event_bus,
)
from src.llm.client import get_llm  # noqa: F401
from src.retrieval.retriever import get_retriever  # noqa: F401
