"""Tests for optional log → string channel forwarding."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]


def _load_logging_forward():
    pkg_name = "custom_components.sift"
    if pkg_name not in sys.modules:
        pkg = type(sys)(pkg_name)
        pkg.__path__ = [str(ROOT / "custom_components" / "sift")]
        sys.modules.setdefault("custom_components", type(sys)("custom_components"))
        sys.modules["custom_components"].__path__ = [str(ROOT / "custom_components")]
        sys.modules[pkg_name] = pkg

    for mod_name, file_name in (
        ("custom_components.sift.const", "const.py"),
        ("custom_components.sift.schemas", "schemas.py"),
        ("custom_components.sift.ingest", "ingest.py"),
        ("custom_components.sift.logging_forward", "logging_forward.py"),
    ):
        path = ROOT / "custom_components" / "sift" / file_name
        spec = importlib.util.spec_from_file_location(mod_name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        assert spec.loader
        spec.loader.exec_module(mod)
    return sys.modules["custom_components.sift.logging_forward"]


async def test_handler_enqueues_and_skips_self():
    lf = _load_logging_forward()
    worker = MagicMock()
    enqueued = []
    worker.enqueue = enqueued.append

    handler = lf.attach_log_handler(
        loop=asyncio.get_running_loop(),
        worker=worker,
        level_name="WARNING",
        loggers=[],
        channel="homeassistant.log",
        max_message_length=200,
    )

    # Bypass root level filtering by invoking handler directly.
    rec_ok = logging.LogRecord(
        "homeassistant.core", logging.WARNING, __file__, 1, "door left open", (), None
    )
    rec_skip = logging.LogRecord(
        "custom_components.sift.ingest",
        logging.ERROR,
        __file__,
        1,
        "should not forward",
        (),
        None,
    )
    if handler.filter(rec_ok):
        handler.emit(rec_ok)
    if handler.filter(rec_skip):
        handler.emit(rec_skip)
    await asyncio.sleep(0)
    lf.detach_log_handler(handler)

    assert len(enqueued) == 1
    assert enqueued[0].channel == "homeassistant.log"
    assert "door left open" in enqueued[0].value
    assert enqueued[0].value.startswith("WARNING")


async def test_secret_redaction_and_truncation():
    lf = _load_logging_forward()
    worker = MagicMock()
    enqueued = []
    worker.enqueue = enqueued.append

    handler = lf.attach_log_handler(
        loop=asyncio.get_running_loop(),
        worker=worker,
        level_name="INFO",
        loggers=["demo"],
        channel="homeassistant.log",
        max_message_length=40,
    )
    rec = logging.LogRecord(
        "demo.mod",
        logging.INFO,
        __file__,
        1,
        "api_key=supersecret value and more text here",
        (),
        None,
    )
    assert handler.filter(rec)
    handler.emit(rec)
    await asyncio.sleep(0)
    lf.detach_log_handler(handler)

    assert len(enqueued) == 1
    assert "supersecret" not in enqueued[0].value
    assert "***" in enqueued[0].value
    assert len(enqueued[0].value) <= 40
