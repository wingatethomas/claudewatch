"""UI safety utilities — crash-proof decorators for PyObjC delegate callbacks."""

from __future__ import annotations

import contextlib
import functools
import logging
from collections.abc import Callable
from typing import TypeVar

import objc
from Foundation import NSObject

log = logging.getLogger("claudewatch")

F = TypeVar("F", bound=Callable)


def objc_callback(fn: F) -> F:  # noqa: UP047
    """Wrap a PyObjC delegate callback with crash-safe error handling.

    Logs exceptions to the audit log instead of letting them crash the app.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        try:
            return fn(*args, **kwargs)
        except Exception:
            log.exception("%s failed", fn.__qualname__)
            return None

    return wrapper  # type: ignore[return-value]


def objc_callback_with_default(default: object = None) -> Callable[[F], F]:
    """Wrap a PyObjC delegate callback, returning a default value on error."""

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            try:
                return fn(*args, **kwargs)
            except Exception:
                log.exception("%s failed", fn.__qualname__)
                return default

        return wrapper  # type: ignore[return-value]

    return decorator  # type: ignore[return-value]


def get_represented_object(sender: object) -> str:
    """Get the representedObject from any AppKit sender (NSMenuItem, NSButton, NSSwitch, etc.)."""
    obj = None
    with contextlib.suppress(AttributeError, TypeError):
        obj = sender.representedObject()  # type: ignore[union-attr]
    if obj is None:
        with contextlib.suppress(AttributeError, TypeError):
            obj = sender.cell().representedObject()  # type: ignore[union-attr]
    return str(obj) if obj is not None else ""


# -- Main thread dispatch ---------------------------------------------------

_trampolines: set[object] = set()  # prevent GC during async dispatch


class _MainThreadTrampoline(NSObject):
    """Helper to dispatch a Python callable to the main thread."""

    _fn: Callable[[], None] | None

    def init(self):  # noqa: ANN201, ANN202
        self = objc.super(_MainThreadTrampoline, self).init()  # noqa: PLW0642
        if self is not None:
            self._fn = None
        return self

    def run_(self, _arg: object) -> None:
        try:
            if self._fn is not None:
                self._fn()
        except Exception:
            log.exception("dispatch_to_main_thread callback failed")
        finally:
            _trampolines.discard(self)


def dispatch_to_main_thread(fn: Callable[[], None]) -> None:
    """Run a callable on the main thread (non-blocking)."""
    trampoline = _MainThreadTrampoline.alloc().init()
    trampoline._fn = fn
    _trampolines.add(trampoline)  # prevent GC
    trampoline.performSelectorOnMainThread_withObject_waitUntilDone_("run:", None, False)
