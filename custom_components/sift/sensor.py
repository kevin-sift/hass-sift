"""Sift diagnostic sensors."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import DATA_STATS, DOMAIN


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up Sift diagnostic sensors."""
    stats = (hass.data.get(DOMAIN) or {}).get(DATA_STATS)
    if not stats:
        return
    async_add_entities(
        [
            SiftStatSensor(stats, "Sift last success", "sift_last_success", "last_success", True),
            SiftStatSensor(
                stats, "Sift consecutive failures", "sift_consecutive_failures", "consecutive_failures"
            ),
            SiftStatSensor(stats, "Sift queue depth", "sift_queue_depth", "queue_depth"),
            SiftStatSensor(stats, "Sift dropped points", "sift_dropped_points", "dropped_points"),
        ]
    )


class SiftStatSensor(SensorEntity):
    """Expose one hass.data[sift][stats] field."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = True

    def __init__(
        self,
        stats: dict[str, Any],
        name: str,
        unique_id: str,
        key: str,
        is_timestamp: bool = False,
    ) -> None:
        self._stats = stats
        self._key = key
        self._is_timestamp = is_timestamp
        self._attr_name = name
        self._attr_unique_id = unique_id
        if is_timestamp:
            self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self):
        value = self._stats.get(self._key)
        if self._is_timestamp:
            if isinstance(value, datetime):
                return value
            return None
        return value
