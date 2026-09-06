"""Ensure custom_components is importable; stub homeassistant for unit tests."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import voluptuous as vol

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _identity(value):
    return value


if "homeassistant" not in sys.modules:
    ha = types.ModuleType("homeassistant")
    const = types.ModuleType("homeassistant.const")
    const.EVENT_STATE_CHANGED = "state_changed"
    const.EVENT_HOMEASSISTANT_STOP = "homeassistant_stop"
    const.STATE_UNAVAILABLE = "unavailable"
    const.STATE_UNKNOWN = "unknown"

    helpers = types.ModuleType("homeassistant.helpers")
    cv = types.ModuleType("homeassistant.helpers.config_validation")
    cv.string = str
    cv.boolean = bool
    cv.ensure_list = lambda x: x if isinstance(x, list) else [x]
    entityfilter = types.ModuleType("homeassistant.helpers.entityfilter")
    entityfilter.FILTER_SCHEMA = vol.Schema({}, extra=vol.ALLOW_EXTRA)

    core = types.ModuleType("homeassistant.core")
    typing_mod = types.ModuleType("homeassistant.helpers.typing")
    typing_mod.ConfigType = dict
    util = types.ModuleType("homeassistant.util")
    dt = types.ModuleType("homeassistant.util.dt")

    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.const"] = const
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.config_validation"] = cv
    sys.modules["homeassistant.helpers.entityfilter"] = entityfilter
    sys.modules["homeassistant.helpers.typing"] = typing_mod
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.util"] = util
    sys.modules["homeassistant.util.dt"] = dt
