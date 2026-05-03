"""Map validated config to HAP bridge children."""

from __future__ import annotations

from typing import Any

from smartrent_homekit.client import SmartRentClient
from smartrent_homekit.config import AppConfig
from smartrent_homekit.hap_devices import (
    SmartRentBridge,
    SmartRentLightAccessory,
    SmartRentLockAccessory,
)


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
