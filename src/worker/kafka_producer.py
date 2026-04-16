"""Backward-compatibility shim → src.tasking.producer

Explicit re-exports keep these names in shim.__dict__ so unittest.mock.patch
sees is_local=True and uses setattr for restore (not delattr).  __setattr__
mirrors every write to the real module so patches propagate correctly.
"""
import sys as _sys
import src.tasking.producer as _mod
from src.tasking.producer import (  # noqa: F401
    publish_task, get_producer, _make_producer, _fallback_thread,
)


class _ProxyModule(_sys.modules[__name__].__class__):
    def __getattr__(self, name):
        return getattr(_mod, name)

    def __setattr__(self, name, value):
        if name.startswith('_ProxyModule') or name == '__class__':
            super().__setattr__(name, value)
        else:
            # Update both the real module and shim's own __dict__ so that
            # `from shim import X` after patching returns the patched value.
            setattr(_mod, name, value)
            super().__setattr__(name, value)


_sys.modules[__name__].__class__ = _ProxyModule
