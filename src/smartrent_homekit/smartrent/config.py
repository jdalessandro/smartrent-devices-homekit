"""Load `devices.json` describing SmartRent devices to mirror in HomeKit."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Literal, Optional

logger = logging.getLogger(__name__)

DeviceType = Literal["light", "lock"]


@dataclass
class DeviceEntry:
    """One row in `devices.json` `devices` array."""

    name: str
    type: DeviceType
    device_id: int
    dimmable: bool = True
    hap_aid: Optional[int] = None


@dataclass
class AppConfig:
    """Top-level configuration including defaults and device list."""

    poll_interval_seconds: float
    devices: List[DeviceEntry]


def load_config(path: Path) -> AppConfig:
    """
    Parse JSON config produced from SmartRent device IDs as used in GET/PATCH URLs.

    :param path: Path to JSON file.
    :returns: Validated configuration.
    :raises ValueError: On invalid structure or unknown device type.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("config root must be an object")

    poll = float(raw.get("poll_interval_seconds", 10.0))
    devices_raw = raw.get("devices")
    if not isinstance(devices_raw, list) or not devices_raw:
        raise ValueError("`devices` must be a non-empty array")

    devices: List[DeviceEntry] = []
    for i, item in enumerate(devices_raw):
        if not isinstance(item, dict):
            raise ValueError(f"devices[{i}] must be an object")
        name = item.get("name")
        typ = item.get("type")
        did = item.get("device_id")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"devices[{i}].name must be a non-empty string")
        if typ not in ("light", "lock"):
            raise ValueError(f"devices[{i}].type must be 'light' or 'lock'")
        if not isinstance(did, int):
            raise ValueError(f"devices[{i}].device_id must be an integer (path segment)")
        dimmable = bool(item.get("dimmable", True))
        if typ == "lock" and dimmable:
            dimmable = False
        hap_aid = item.get("hap_aid")
        if hap_aid is not None and not isinstance(hap_aid, int):
            raise ValueError(f"devices[{i}].hap_aid must be int or omitted")

        devices.append(
            DeviceEntry(
                name=name.strip(),
                type=typ,
                device_id=did,
                dimmable=dimmable if typ == "light" else False,
                hap_aid=hap_aid,
            )
        )

    logger.info("Loaded %s devices from %s", len(devices), path)
    return AppConfig(poll_interval_seconds=poll, devices=devices)


def config_to_dict(cfg: AppConfig) -> dict[str, Any]:
    """Serialize config for logging or tests."""
    return {
        "poll_interval_seconds": cfg.poll_interval_seconds,
        "devices": [
            {
                "name": d.name,
                "type": d.type,
                "device_id": d.device_id,
                "dimmable": d.dimmable,
                **({"hap_aid": d.hap_aid} if d.hap_aid is not None else {}),
            }
            for d in cfg.devices
        ],
    }
