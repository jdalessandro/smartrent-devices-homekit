"""Shared parsing helpers for the interactive setup wizard (TUI and tests)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def unit_id_and_label(unit: Dict[str, Any]) -> Optional[Tuple[int, str]]:
    """Return ``(id, display_label)`` for a unit object, or None if unusable."""
    uid = unit.get("id")
    if isinstance(uid, str) and uid.isdigit():
        uid = int(uid)
    if not isinstance(uid, int):
        return None
    name = (
        unit.get("name")
        or unit.get("title")
        or unit.get("marketing_name")
        or unit.get("unit_code")
        or unit.get("unit_number")
    )
    label = str(name).strip() if name is not None else f"Unit {uid}"
    return uid, label


def device_summary(dev: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract id, name, API ``type``, and HomeKit role.

    ``role`` is ``light``, ``lock``, or None when the device is not exposed to HomeKit.
    """
    did = dev.get("id")
    if isinstance(did, str) and did.isdigit():
        did = int(did)
    if not isinstance(did, int):
        return None
    name = dev.get("name") or dev.get("title") or str(did)
    api_type = dev.get("type")
    if not isinstance(api_type, str):
        api_type = ""

    role: Optional[str] = None
    dimmable = False
    if api_type == "switch_multilevel":
        role = "light"
        dimmable = True
    elif api_type == "switch_binary":
        role = "light"
        dimmable = False
    elif api_type == "entry_control":
        role = "lock"
        dimmable = False

    return {
        "id": did,
        "name": str(name).strip() or str(did),
        "api_type": api_type or "unknown",
        "role": role,
        "dimmable": dimmable,
    }


def unit_rows(units: List[Dict[str, Any]]) -> List[Tuple[int, str]]:
    """Build ordered ``(unit_id, label)`` rows from API unit dicts."""
    rows: List[Tuple[int, str]] = []
    for u in units:
        parsed = unit_id_and_label(u)
        if parsed is not None:
            rows.append(parsed)
    return rows


def device_summaries_list(devices: List[Any]) -> List[Optional[Dict[str, Any]]]:
    """One entry per API device row; ``None`` for malformed rows."""
    out: List[Optional[Dict[str, Any]]] = []
    for dev in devices:
        if not isinstance(dev, dict):
            out.append(None)
        else:
            out.append(device_summary(dev))
    return out


def device_row_label(index: int, summ: Optional[Dict[str, Any]]) -> str:
    """Single-line label for the device picker (1-based index)."""
    n = index + 1
    if summ is None:
        return f"{n}.  (invalid row)"
    did = summ["id"]
    name = summ["name"]
    api_t = summ["api_type"]
    role = summ["role"]
    hk = role or "not supported"
    return f"{n}.  {name}  |  {api_t}  |  HomeKit: {hk}"
