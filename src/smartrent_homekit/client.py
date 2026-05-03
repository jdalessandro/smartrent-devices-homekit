"""HTTP client for the SmartRent control API (see `constants.py` for paths)."""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
from typing import Any, Dict, Optional

import httpx

from smartrent_homekit.constants import (
    AUTH_EXTRA_HEADERS,
    CONTROL_BASE,
    DEVICES_API_PREFIX,
    SESSIONS_PATH,
    TOKEN_FALLBACK_TTL_MS,
)

logger = logging.getLogger(__name__)


def _extract_access_token(body: Dict[str, Any]) -> Optional[str]:
    """Return bearer token from `access_token`, `token`, or `data.access_token`."""
    token = body.get("access_token") or body.get("token")
    if token is None and isinstance(body.get("data"), dict):
        token = body["data"].get("access_token")
    if isinstance(token, str) and token:
        return token
    return None


def _jwt_expiry_ms(token: str) -> Optional[int]:
    """Return access token expiry in ms from JWT `exp` claim, if present."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload_b64 = parts[1]
    pad = "=" * (-len(payload_b64) % 4)
    try:
        raw = base64.urlsafe_b64decode(payload_b64 + pad)
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, OSError):
        return None
    exp = payload.get("exp")
    if isinstance(exp, (int, float)):
        return int(exp * 1000)
    return None


class SmartRentClient:
    """
    Thread-safe client: POST /authentication/sessions, GET/PATCH /api/v2/devices/{id}.

    Token refresh runs when the token is missing, past computed expiry, or after
    HTTP 401 (single retry).
    """

    def __init__(self, email: str, password: str) -> None:
        self._email = email
        self._password = password
        self._lock = threading.Lock()
        self._token: Optional[str] = None
        self._token_expiry_ms: Optional[int] = None
        self._client = httpx.Client(base_url=CONTROL_BASE, timeout=30.0)

    def close(self) -> None:
        self._client.close()

    def _set_token_unlocked(self, token: str) -> None:
        self._token = token
        fallback_deadline = int(time.time() * 1000) + TOKEN_FALLBACK_TTL_MS
        jwt_deadline = _jwt_expiry_ms(token)
        if jwt_deadline is not None:
            self._token_expiry_ms = min(fallback_deadline, jwt_deadline - 60_000)
        else:
            self._token_expiry_ms = fallback_deadline

    def _needs_refresh_unlocked(self) -> bool:
        if not self._token or self._token_expiry_ms is None:
            return True
        return time.time() * 1000 > self._token_expiry_ms

    def refresh_token(self) -> None:
        """
        POST JSON {email, password} to /authentication/sessions (no auth header).

        :raises httpx.HTTPError: On transport errors.
        :raises RuntimeError: When response has no usable access token.
        """
        body_obj = {"email": self._email, "password": self._password}
        headers = {"Content-Type": "application/json", **AUTH_EXTRA_HEADERS}
        resp = self._client.post(
            SESSIONS_PATH,
            json=body_obj,
            headers=headers,
        )
        resp.raise_for_status()
        body = resp.json()
        token = _extract_access_token(body)
        if not token:
            raise RuntimeError("authentication/sessions response missing access token")
        with self._lock:
            self._set_token_unlocked(token)
        logger.info("Obtained new SmartRent access token")

    def _ensure_token(self) -> str:
        with self._lock:
            if not self._needs_refresh_unlocked():
                assert self._token is not None
                return self._token
        self.refresh_token()
        with self._lock:
            assert self._token is not None
            return self._token

    def _auth_headers(self, include_json_content_type: bool) -> Dict[str, str]:
        token = self._ensure_token()
        h: Dict[str, str] = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/plain, */*",
        }
        if include_json_content_type:
            h["Content-Type"] = "application/json"
        return h

    def _device_path(self, device_id: int) -> str:
        return f"{DEVICES_API_PREFIX}/{device_id}"

    def get_device(self, device_id: int) -> Dict[str, Any]:
        """
        GET /api/v2/devices/{device_id}.

        :returns: Parsed JSON object (device payload).
        """
        return self._request_json("GET", self._device_path(device_id), json_body=None)

    def patch_attributes(self, device_id: int, attributes: list) -> Dict[str, Any]:
        """
        PATCH /api/v2/devices/{device_id} with body {"attributes": [...]}.

        Each attribute is ``{"name": str, "state": str}`` (e.g. ``level``, ``locked``).
        """
        payload = {"attributes": attributes}
        return self._request_json(
            "PATCH",
            self._device_path(device_id),
            json_body=payload,
        )

    def _request_json(
        self,
        method: str,
        path: str,
        json_body: Optional[dict],
    ) -> Dict[str, Any]:
        def once() -> httpx.Response:
            headers = self._auth_headers(include_json_content_type=method != "GET")
            if method == "GET":
                return self._client.request(method, path, headers=headers)
            return self._client.request(method, path, headers=headers, json=json_body)

        resp = once()
        if resp.status_code == 401:
            logger.warning("SmartRent returned 401; refreshing token and retrying once")
            self.refresh_token()
            resp = once()
        resp.raise_for_status()
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()
