"""Sift schemaless channel naming helpers."""

from __future__ import annotations

from typing import Mapping


def resolve_sift_channel(
    entity_id: str,
    *,
    attr: str | None = None,
    channel_map: Mapping[str, str] | None = None,
) -> str:
    """Resolve the Sift channel for an entity state or attribute.

    Single-name resolve (no dual-publish):
    * base = ``channel_map.get(entity_id, entity_id)``
    * state → ``base``
    * attribute → ``f"{base}.{attr}"``

    Empty / absent map leaves names as today's ``entity_id`` /
    ``{entity_id}.{attr}`` behavior.
    """
    base = (channel_map or {}).get(entity_id, entity_id)
    if attr is None:
        return base
    return f"{base}.{attr}"
