"""Map validated config to HAP bridge children."""

from __future__ import annotations

from typing import Any

from smartrent_homekit.homekit.accessories import (
    SmartRentBridge,
    SmartRentLightAccessory,
    SmartRentLockAccessory,
)
from smartrent_homekit.smartrent.client import SmartRentClient
from smartrent_homekit.smartrent.config import AppConfig


class DeviceRegistry:
    """
    Holds application config and attaches one HAP accessory per SmartRent device
    to the bridge.
    """

    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg

    def attach_to_bridge(
        self,
        driver: Any,
        bridge: SmartRentBridge,
        client: SmartRentClient,
    ) -> None:
        """Create and register managed accessories according to ``devices.json``."""
        for entry in self.cfg.devices:
            if entry.type == "light":
                bridge.add_managed(SmartRentLightAccessory(driver, entry, client))
            else:
                bridge.add_managed(SmartRentLockAccessory(driver, entry, client))
