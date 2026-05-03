"""On-disk preferences and ``smartrent.env`` for SmartRent credentials."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from platformdirs import user_config_dir

logger = logging.getLogger(__name__)

CREDENTIALS_ENV_FILENAME = "smartrent.env"


def config_dir() -> Path:
    """Directory for ``config.json`` (e.g. ``~/.config/smartrent-homekit`` on Linux)."""
    p = Path(user_config_dir("smartrent-homekit", appauthor=False))
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_path() -> Path:
    return config_dir() / "config.json"


def load_config_file() -> Dict[str, Any]:
    path = config_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Could not read %s: %s", path, e)
        return {}


def save_config_file(data: Dict[str, Any]) -> None:
    path = config_path()
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def get_saved_email() -> Optional[str]:
    email = load_config_file().get("email")
    return email if isinstance(email, str) and email else None


def save_email(email: str) -> None:
    cfg = load_config_file()
    cfg["email"] = email.strip()
    save_config_file(cfg)


def save_last_unit_id(unit_id: int) -> None:
    cfg = load_config_file()
    cfg["last_unit_id"] = unit_id
    save_config_file(cfg)


def get_last_unit_id() -> Optional[int]:
    raw = load_config_file().get("last_unit_id")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    return None


def save_credentials_env_path(env_path: Path) -> None:
    """Record absolute path to ``smartrent.env`` for cleanup and documentation."""
    cfg = load_config_file()
    cfg["credentials_env_path"] = str(env_path.resolve())
    save_config_file(cfg)


def get_credentials_env_path() -> Optional[Path]:
    raw = load_config_file().get("credentials_env_path")
    if isinstance(raw, str) and raw.strip():
        return Path(raw).expanduser()
    return None


def _unquote_env_value(raw: str) -> str:
    s = raw.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    return s


def apply_smartrent_env_file(path: Path) -> None:
    """
    Load ``SMARTRENT_*`` keys from a ``smartrent.env`` file into ``os.environ``
    only when those keys are not already set.
    """
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("Could not read env file %s: %s", path, e)
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not key.startswith("SMARTRENT_"):
            continue
        if key in os.environ and os.environ[key]:
            continue
        os.environ[key] = _unquote_env_value(val)


def write_credentials_env_file(
    devices_json: Path,
    email: str,
    password: str,
) -> Path:
    """
    Write ``smartrent.env`` next to ``devices.json`` with chmod 0600.

    Values are double-quoted with minimal escaping for ``systemd EnvironmentFile``
    and for ``set -a; . ./smartrent.env`` in bash/zsh.
    """
    env_path = devices_json.parent / CREDENTIALS_ENV_FILENAME
    resolved_devices = str(devices_json.resolve())

    def _line(name: str, value: str) -> str:
        esc = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'{name}="{esc}"'

    body = "\n".join(
        [
            _line("SMARTRENT_EMAIL", email.strip()),
            _line("SMARTRENT_PASSWORD", password),
            _line("SMARTRENT_CONFIG", resolved_devices),
            "",
        ]
    )
    env_path.write_text(body, encoding="utf-8")
    try:
        env_path.chmod(0o600)
    except OSError:
        pass
    return env_path.resolve()
