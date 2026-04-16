"""Backward-compatibility shim — re-exports from new canonical locations.

New code should import from:
  src.chat.service         — session/message CRUD
  src.investigations.service — saved search / investigation CRUD
"""
from src.chat.service import (  # noqa: F401
    create_session,
    get_session,
    list_sessions,
    update_session_title,
    delete_session,
    append_message,
    get_messages,
    get_recent_messages,
)
from src.investigations.service import (  # noqa: F401
    list_saved_searches,
    create_saved_search,
    update_saved_search,
    delete_saved_search,
    get_saved_search,
    list_investigations,
    create_investigation,
    get_investigation,
    update_investigation_status,
    delete_investigation,
)
