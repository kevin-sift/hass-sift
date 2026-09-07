"""Opt-in allowlist for Hybrid B typed IngestionConfig channels.

Allowlisted entities register ChannelConfig (unit + optional description) and
stream via ingestion-config gRPC. Everything else stays on schemaless REST.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .const import (
    CONF_TYPED_DATA_TYPE,
    CONF_TYPED_DESCRIPTION,
    CONF_TYPED_ENTITY_ID,
    CONF_TYPED_UNIT,
)

_LOGGER = logging.getLogger(__name__)

# Prefer HA unit_of_measurement; fall back to a few device_class defaults when
# the attribute is missing (temperature uses °C only as last resort — Limburg
# Home sensors usually set unit_of_measurement explicitly, often °F).
_DEVICE_CLASS_UNIT: dict[str, str] = {
    "temperature": "°C",
    "humidity": "%",
    "pressure": "Pa",
    "illuminance": "lx",
    "power": "W",
    "energy": "kWh",
    "voltage": "V",
    "current": "A",
    "battery": "%",
    "carbon_dioxide": "ppm",
    "volatile_organic_compounds": "µg/m³",
    "pm25": "µg/m³",
    "pm10": "µg/m³",
}

_ATTR_UNIT = "unit_of_measurement"
_ATTR_DEVICE_CLASS = "device_class"
_ATTR_FRIENDLY_NAME = "friendly_name"


@dataclass(frozen=True, slots=True)
class TypedChannelSpec:
    """One allowlisted entity → typed ChannelConfig inputs."""

    entity_id: str
    unit: str | None = None
    description: str | None = None
    data_type: str | None = None  # double|float|bool|string|…; None = infer


@dataclass(frozen=True, slots=True)
class ResolvedChannel:
    """Concrete ChannelConfig fields after HA attribute resolution."""

    entity_id: str
    unit: str
    description: str
    data_type: str  # normalized lower-case name


def flow_name_for(entity_id: str) -> str:
    """Stable flow name for one entity (one channel per flow → additive BC)."""
    return f"ha_typed.{entity_id}"


def infer_data_type(value: float | str | bool, explicit: str | None = None) -> str:
    """Pick a ChannelDataType name for the value (or honor explicit override)."""
    if explicit:
        return explicit.lower()
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "double"
    return "string"


def resolve_unit(
    *,
    attributes: Mapping[str, Any] | None,
    override: str | None = None,
) -> str:
    """Resolve unit string: YAML override → unit_of_measurement → device_class."""
    if override:
        return override
    attrs = attributes or {}
    uom = attrs.get(_ATTR_UNIT)
    if isinstance(uom, str) and uom.strip():
        return uom.strip()
    device_class = attrs.get(_ATTR_DEVICE_CLASS)
    if isinstance(device_class, str):
        mapped = _DEVICE_CLASS_UNIT.get(device_class)
        if mapped:
            return mapped
    return ""


def resolve_description(
    *,
    entity_id: str,
    attributes: Mapping[str, Any] | None,
    override: str | None = None,
) -> str:
    """Resolve optional description: YAML → friendly_name → entity_id."""
    if override:
        return override
    attrs = attributes or {}
    name = attrs.get(_ATTR_FRIENDLY_NAME)
    if isinstance(name, str) and name.strip():
        return name.strip()
    return entity_id


def resolve_channel(
    spec: TypedChannelSpec,
    *,
    value: float | str | bool,
    attributes: Mapping[str, Any] | None = None,
) -> ResolvedChannel:
    """Build ResolvedChannel for registration / send."""
    return ResolvedChannel(
        entity_id=spec.entity_id,
        unit=resolve_unit(attributes=attributes, override=spec.unit),
        description=resolve_description(
            entity_id=spec.entity_id,
            attributes=attributes,
            override=spec.description,
        ),
        data_type=infer_data_type(value, spec.data_type),
    )


class TypedChannelAllowlist:
    """entity_id → TypedChannelSpec lookup (empty == schemaless-only default)."""

    def __init__(self, specs: Mapping[str, TypedChannelSpec] | None = None) -> None:
        self._specs = dict(specs or {})

    @classmethod
    def from_config(
        cls, entries: Iterable[Mapping[str, Any]] | None
    ) -> TypedChannelAllowlist:
        specs: dict[str, TypedChannelSpec] = {}
        for entry in entries or ():
            entity_id = entry.get(CONF_TYPED_ENTITY_ID)
            if not entity_id or not isinstance(entity_id, str):
                continue
            specs[entity_id] = TypedChannelSpec(
                entity_id=entity_id,
                unit=entry.get(CONF_TYPED_UNIT),
                description=entry.get(CONF_TYPED_DESCRIPTION),
                data_type=entry.get(CONF_TYPED_DATA_TYPE),
            )
        return cls(specs)

    def __bool__(self) -> bool:
        return bool(self._specs)

    def __len__(self) -> int:
        return len(self._specs)

    def __contains__(self, entity_id: str) -> bool:
        return entity_id in self._specs

    def get(self, entity_id: str) -> TypedChannelSpec | None:
        return self._specs.get(entity_id)

    def entity_ids(self) -> frozenset[str]:
        return frozenset(self._specs)

    def fingerprint(self, resolved: ResolvedChannel) -> tuple[str, str, str]:
        """Immutable identity for schema guard (name, unit, data_type)."""
        return (resolved.entity_id, resolved.unit, resolved.data_type)
