"""
HomeKit (HAP-python) bridge and accessories driven by SmartRent GET/PATCH.

Characteristic semantics follow Apple HAP; device payloads use SmartRent
attributes ``level`` and ``locked`` with string state values.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from pyhap.accessory import Accessory, Bridge
from pyhap.const import CATEGORY_DOOR_LOCK, CATEGORY_LIGHTBULB

from smartrent_homekit.smartrent.client import SmartRentClient
from smartrent_homekit.smartrent.config import AppConfig, DeviceEntry

logger = logging.getLogger(__name__)


def _attribute_state_map(device_json: Dict[str, Any]) -> Dict[str, str]:
    """Map SmartRent ``attributes`` array entries to ``name -> state`` strings."""
    out: Dict[str, str] = {}
    for item in device_json.get("attributes") or []:
        if isinstance(item, dict) and "name" in item:
            name = item.get("name")
            state = item.get("state")
            if isinstance(name, str):
                out[name] = "" if state is None else str(state)
    return out


class SmartRentManagedAccessory(Accessory):
    """Common wiring: SmartRent numeric `device_id` and shared HTTP client."""

    def __init__(
        self,
        driver: Any,
        entry: DeviceEntry,
        client: SmartRentClient,
    ) -> None:
        super().__init__(driver, entry.name, aid=entry.hap_aid)
        self.entry = entry
        self.client = client
        self.device_id = entry.device_id

    def apply_device_json(self, data: Dict[str, Any]) -> None:
        """Override: map GET /api/v2/devices/{id} JSON into HAP characteristics."""
        raise NotImplementedError


class SmartRentLightAccessory(SmartRentManagedAccessory):
    """Dimmable or on/off light using PATCH attribute `level` (string 0–100)."""

    category = CATEGORY_LIGHTBULB

    def __init__(
        self,
        driver: Any,
        entry: DeviceEntry,
        client: SmartRentClient,
    ) -> None:
        super().__init__(driver, entry, client)
        self._last_nonzero_brightness = 100
        serv = self.driver.loader.get_service("Lightbulb")
        self._serv_light = serv
        if entry.dimmable:
            serv.add_characteristic(self.driver.loader.get_char("Brightness"))
        self.add_service(serv)
        serv.configure_char("On", setter_callback=self._set_on)
        if entry.dimmable:
            serv.configure_char("Brightness", setter_callback=self._set_brightness)
        self.set_info_service(
            manufacturer="SmartRent",
            model="switch_multilevel",
            serial_number=str(entry.device_id),
            firmware_revision="1.0.0",
        )

    def _set_on(self, value: bool) -> None:
        if value:
            level = self._last_nonzero_brightness if self.entry.dimmable else 100
            self.client.patch_attributes(
                self.device_id,
                [{"name": "level", "state": str(int(level))}],
            )
        else:
            self.client.patch_attributes(
                self.device_id,
                [{"name": "level", "state": "0"}],
            )

    def _set_brightness(self, value: int) -> None:
        b = int(value)
        self._last_nonzero_brightness = max(1, min(100, b))
        self.client.patch_attributes(
            self.device_id,
            [{"name": "level", "state": str(self._last_nonzero_brightness)}],
        )

    def apply_device_json(self, data: Dict[str, Any]) -> None:
        attrs = _attribute_state_map(data)
        raw_level = attrs.get("level", "0")
        try:
            level = int(float(raw_level))
        except (TypeError, ValueError):
            level = 0
        level = max(0, min(100, level))
        on = level > 0
        if on and self.entry.dimmable:
            self._last_nonzero_brightness = max(level, 1)

        char_on = self._serv_light.get_characteristic("On")
        char_on.set_value(bool(on), should_notify=True)
        if self.entry.dimmable:
            char_b = self._serv_light.get_characteristic("Brightness")
            char_b.set_value(level, should_notify=True)


class SmartRentLockAccessory(SmartRentManagedAccessory):
    """Lock using PATCH attribute `locked` with string \"true\" / \"false\"."""

    category = CATEGORY_DOOR_LOCK

    LOCK_SECURED = 1
    LOCK_UNSECURED = 0

    def __init__(
        self,
        driver: Any,
        entry: DeviceEntry,
        client: SmartRentClient,
    ) -> None:
        super().__init__(driver, entry, client)
        serv = self.driver.loader.get_service("LockMechanism")
        self._serv_lock = serv
        self.add_service(serv)
        serv.configure_char("LockTargetState", setter_callback=self._set_lock_target)
        self.set_info_service(
            manufacturer="SmartRent",
            model="entry_control",
            serial_number=str(entry.device_id),
            firmware_revision="1.0.0",
        )

    def _set_lock_target(self, value: int) -> None:
        locked = value == self.LOCK_SECURED
        self.client.patch_attributes(
            self.device_id,
            [{"name": "locked", "state": "true" if locked else "false"}],
        )

    def apply_device_json(self, data: Dict[str, Any]) -> None:
        attrs = _attribute_state_map(data)
        locked = attrs.get("locked", "false").lower() == "true"
        cur = self.LOCK_SECURED if locked else self.LOCK_UNSECURED
        self._serv_lock.get_characteristic("LockCurrentState").set_value(
            cur, should_notify=True
        )
        self._serv_lock.get_characteristic("LockTargetState").set_value(
            cur, should_notify=True
        )


class SmartRentBridge(Bridge):
    """
    HAP bridge that owns one HTTP client and polls each device on an interval.

    Polling uses ``GET /api/v2/devices/{id}`` for every managed accessory.
    """

    def __init__(
        self,
        driver: Any,
        display_name: str,
        client: SmartRentClient,
        cfg: AppConfig,
    ) -> None:
        super().__init__(driver, display_name)
        self._client = client
        self._poll_interval = cfg.poll_interval_seconds
        self._poll_task: Optional[asyncio.Task] = None
        self._managed: List[SmartRentManagedAccessory] = []

    def add_managed(self, acc: SmartRentManagedAccessory) -> None:
        self.add_accessory(acc)
        self._managed.append(acc)

    async def run(self) -> None:
        await super().run()
        loop = asyncio.get_event_loop()
        for acc in self._managed:
            try:
                data = await loop.run_in_executor(
                    None,
                    self._client.get_device,
                    acc.device_id,
                )
            except Exception:
                logger.exception("Initial GET device %s failed", acc.device_id)
                continue
            if isinstance(data, dict):
                acc.apply_device_json(data)
        self._poll_task = asyncio.create_task(self._poll_loop(), name="smartrent-poll")

    async def _poll_loop(self) -> None:
        loop = asyncio.get_event_loop()
        while True:
            await asyncio.sleep(self._poll_interval)
            for acc in self._managed:
                try:
                    data = await loop.run_in_executor(
                        None,
                        self._client.get_device,
                        acc.device_id,
                    )
                except Exception:
                    logger.exception("GET device %s failed", acc.device_id)
                    continue
                if isinstance(data, dict):
                    acc.apply_device_json(data)

    async def stop(self) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        await super().stop()
