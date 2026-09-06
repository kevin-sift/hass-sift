"""Sift health and heartbeat binary sensors."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    CONF_HEALTH_STALE_AFTER,
    DATA_STATS,
    DEFAULT_HEALTH_STALE_AFTER,
    DOMAIN,
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up Sift binary sensors (YAML discovery)."""
    if discovery_info is None and config.get(DOMAIN) is None:
        # Loaded via discovery from async_setup
        pass
    data = hass.data.get(DOMAIN) or {}
    stats = data.get(DATA_STATS)
    if not stats:
        return
    stale_after = data.get(CONF_HEALTH_STALE_AFTER, DEFAULT_HEALTH_STALE_AFTER)
    entities: list[BinarySensorEntity] = [
        SiftIngestOkBinarySensor(stats, stale_after),
    ]
    if data.get("heartbeat_entity"):
        entities.append(data["heartbeat_entity"])
    async_add_entities(entities)


class SiftIngestOkBinarySensor(BinarySensorEntity):
    """On when last successful ingest is fresh and auth is OK."""

    _attr_name = "Sift ingest OK"
    _attr_unique_id = "sift_ingest_ok"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = True

    def __init__(self, stats: dict[str, Any], stale_after: int) -> None:
        self._stats = stats
        self._stale_after = stale_after

    @property
    def is_on(self) -> bool:
        if self._stats.get("auth_failed"):
            return False
        last = self._stats.get("last_success")
        if last is None:
            return False
        if isinstance(last, str):
            return False
        age = (datetime.now(timezone.utc) - last).total_seconds()
        return age <= self._stale_after

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        last = self._stats.get("last_success")
        return {
            "last_success": last.isoformat() if hasattr(last, "isoformat") else last,
            "consecutive_failures": self._stats.get("consecutive_failures"),
            "auth_failed": self._stats.get("auth_failed"),
            "stale_after_seconds": self._stale_after,
            "current_run_client_key": self._stats.get("current_run_client_key"),
        }


class SiftHeartbeatBinarySensor(BinarySensorEntity):
    """Toggles on an interval to prove change-only ingest is alive."""

    _attr_name = "Sift heartbeat"
    _attr_unique_id = "sift_heartbeat"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self) -> None:
        self._is_on = False

    @property
    def is_on(self) -> bool:
        return self._is_on

    def toggle(self) -> None:
        self._is_on = not self._is_on
