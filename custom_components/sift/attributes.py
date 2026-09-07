"""Opt-in entity attribute → Sift schemaless channel forwarding."""

from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN

from .const import (
    CONF_ATTR_ATTRIBUTES,
    CONF_ATTR_DOMAIN,
    CONF_ATTR_ENTITY_ID,
)
from .ingest import IngestPoint
from .schemas import STATE_VALUE_SCHEMA

_LOGGER = logging.getLogger(__name__)

_SKIP_VALUES = frozenset({STATE_UNKNOWN, STATE_UNAVAILABLE, ""})


def coerce_attr_value(raw: Any) -> float | str | bool | None:
    """Coerce like entity state; return None to skip."""
    if raw is None:
        return None
    if isinstance(raw, str) and raw in _SKIP_VALUES:
        return None
    try:
        return STATE_VALUE_SCHEMA(raw)
    except Exception:  # noqa: BLE001
        return None


class AttributeAllowlist:
    """Lookup of which attributes to forward for an entity_id / domain."""

    def __init__(
        self,
        *,
        by_entity: Mapping[str, frozenset[str]] | None = None,
        by_domain: Mapping[str, frozenset[str]] | None = None,
    ) -> None:
        self._by_entity = dict(by_entity or {})
        self._by_domain = dict(by_domain or {})

    @classmethod
    def from_config(cls, entries: Iterable[Mapping[str, Any]] | None) -> AttributeAllowlist:
        """Build from YAML list of {entity_id|domain, attributes: [...]}."""
        by_entity: dict[str, set[str]] = {}
        by_domain: dict[str, set[str]] = {}
        for entry in entries or ():
            attrs = {a for a in entry.get(CONF_ATTR_ATTRIBUTES, []) if a}
            if not attrs:
                continue
            entity_id = entry.get(CONF_ATTR_ENTITY_ID)
            domain = entry.get(CONF_ATTR_DOMAIN)
            if entity_id:
                by_entity.setdefault(entity_id, set()).update(attrs)
            elif domain:
                by_domain.setdefault(domain, set()).update(attrs)
        return cls(
            by_entity={k: frozenset(v) for k, v in by_entity.items()},
            by_domain={k: frozenset(v) for k, v in by_domain.items()},
        )

    def __bool__(self) -> bool:
        return bool(self._by_entity or self._by_domain)

    def attrs_for(self, entity_id: str) -> frozenset[str]:
        """Union of entity-specific and domain-level allowlisted attribute names."""
        names: set[str] = set(self._by_entity.get(entity_id, ()))
        domain = entity_id.partition(".")[0]
        names.update(self._by_domain.get(domain, ()))
        return frozenset(names)

    def points_for(
        self,
        *,
        entity_id: str,
        attributes: Mapping[str, Any],
        timestamp: str,
    ) -> list[IngestPoint]:
        """Build ingest points for allowlisted attributes present on the state.

        Channel naming: ``{entity_id}.{attr}`` (e.g. ``climate.thermostat.hvac_action``).
        """
        wanted = self.attrs_for(entity_id)
        if not wanted:
            return []
        points: list[IngestPoint] = []
        for attr in wanted:
            if attr not in attributes:
                continue
            value = coerce_attr_value(attributes[attr])
            if value is None:
                _LOGGER.debug(
                    "Skipping attribute %s.%s (missing/unusable value)",
                    entity_id,
                    attr,
                )
                continue
            points.append(
                IngestPoint(
                    timestamp=timestamp,
                    channel=f"{entity_id}.{attr}",
                    value=value,
                )
            )
        return points
