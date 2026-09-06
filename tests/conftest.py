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
    const.Platform = types.SimpleNamespace(
        BINARY_SENSOR="binary_sensor",
        SENSOR="sensor",
    )

    helpers = types.ModuleType("homeassistant.helpers")
    cv = types.ModuleType("homeassistant.helpers.config_validation")
    cv.string = str
    cv.boolean = bool
    cv.ensure_list = lambda x: x if isinstance(x, list) else [x]
    entityfilter = types.ModuleType("homeassistant.helpers.entityfilter")
    entityfilter.FILTER_SCHEMA = vol.Schema({}, extra=vol.ALLOW_EXTRA)

    core = types.ModuleType("homeassistant.core")

    def callback(fn):
        return fn

    core.callback = callback
    core.HomeAssistant = object
    core.Event = object
    core.State = object

    typing_mod = types.ModuleType("homeassistant.helpers.typing")
    typing_mod.ConfigType = dict
    typing_mod.DiscoveryInfoType = dict

    util = types.ModuleType("homeassistant.util")
    dt = types.ModuleType("homeassistant.util.dt")

    discovery = types.ModuleType("homeassistant.helpers.discovery")

    async def async_load_platform(*_a, **_k):
        return None

    discovery.async_load_platform = async_load_platform

    event_mod = types.ModuleType("homeassistant.helpers.event")

    def async_track_time_interval(*_a, **_k):
        return lambda: None

    event_mod.async_track_time_interval = async_track_time_interval

    entity = types.ModuleType("homeassistant.helpers.entity")

    class EntityCategory:
        DIAGNOSTIC = "diagnostic"

    entity.EntityCategory = EntityCategory

    entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    entity_platform.AddEntitiesCallback = object

    components = types.ModuleType("homeassistant.components")
    binary_sensor = types.ModuleType("homeassistant.components.binary_sensor")

    class BinarySensorDeviceClass:
        CONNECTIVITY = "connectivity"

    class BinarySensorEntity:
        hass = None

        def async_write_ha_state(self):
            return None

    binary_sensor.BinarySensorDeviceClass = BinarySensorDeviceClass
    binary_sensor.BinarySensorEntity = BinarySensorEntity

    sensor = types.ModuleType("homeassistant.components.sensor")

    class SensorDeviceClass:
        TIMESTAMP = "timestamp"

    class SensorEntity:
        hass = None

    sensor.SensorDeviceClass = SensorDeviceClass
    sensor.SensorEntity = SensorEntity

    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.const"] = const
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.config_validation"] = cv
    sys.modules["homeassistant.helpers.entityfilter"] = entityfilter
    sys.modules["homeassistant.helpers.typing"] = typing_mod
    sys.modules["homeassistant.helpers.discovery"] = discovery
    sys.modules["homeassistant.helpers.event"] = event_mod
    sys.modules["homeassistant.helpers.entity"] = entity
    sys.modules["homeassistant.helpers.entity_platform"] = entity_platform
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.util"] = util
    sys.modules["homeassistant.util.dt"] = dt
    sys.modules["homeassistant.components"] = components
    sys.modules["homeassistant.components.binary_sensor"] = binary_sensor
    sys.modules["homeassistant.components.sensor"] = sensor
