"""CLI entry: load config, pair HAP bridge, poll SmartRent."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from pyhap.accessory_driver import AccessoryDriver

from smartrent_homekit.client import SmartRentClient
from smartrent_homekit.config import load_config
from smartrent_homekit.hap_devices import SmartRentBridge
from smartrent_homekit.registry import DeviceRegistry


def _pincode_from_env() -> bytes:
    raw = os.environ.get("SMARTRENT_HAP_PINCODE", "031-45-154")
    return raw.encode("ascii")


def main() -> None:
    level_name = os.environ.get("SMARTRENT_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log = logging.getLogger("smartrent_homekit")

    config_path = Path(
        os.environ.get("SMARTRENT_CONFIG", "devices.json")
    ).expanduser()
    if not config_path.is_file():
        log.error("Config not found: %s", config_path)
        sys.exit(1)

    try:
        email = os.environ["SMARTRENT_EMAIL"]
        password = os.environ["SMARTRENT_PASSWORD"]
    except KeyError:
        log.error("Set SMARTRENT_EMAIL and SMARTRENT_PASSWORD in the environment.")
        sys.exit(1)

    cfg = load_config(config_path)
    registry = DeviceRegistry(cfg)
    port = int(os.environ.get("SMARTRENT_HAP_PORT", "51827"))
    persist = os.path.expanduser(
        os.environ.get("SMARTRENT_HAP_PERSIST", "~/.smartrent_homekit.state")
    )

    client = SmartRentClient(email=email, password=password)
    try:
        client.refresh_token()
    except Exception:
        log.exception("Initial authentication failed")
        sys.exit(1)

    driver = AccessoryDriver(
        port=port,
        persist_file=persist,
        pincode=_pincode_from_env(),
    )
    bridge = SmartRentBridge(driver, "SmartRent", client, cfg)
    registry.attach_to_bridge(driver, bridge, client)

    driver.add_accessory(bridge)

    log.info(
        "Starting HAP on port %s (persist %s); poll every %ss",
        port,
        persist,
        cfg.poll_interval_seconds,
    )
    try:
        driver.start()
    except KeyboardInterrupt:
        pass
    finally:
        client.close()


if __name__ == "__main__":
    main()
