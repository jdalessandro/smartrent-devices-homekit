"""HTTP client for the SmartRent control API (see ``constants`` for paths)."""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Union

import httpx

from smartrent_homekit.smartrent.constants import (
    AUTH_EXTRA_HEADERS,
    CONTROL_BASE,
    DEVICES_API_PREFIX,
    SESSIONS_PATH,
    TOKEN_FALLBACK_TTL_MS,
    UNITS_PATH,
    unit_devices_path,
)

logger = logging.getLogger(__name__)

_RawJSON = Union[Dict[str, Any], List[Any]]


def _normalize_list_payload(payload: _RawJSON) -> List[Any]:
    """
    Normalize list APIs: bare list, or envelopes such as ``{"records": [...]}``,
    ``{"data": [...]}``, ``{"devices": [...]}``, etc.
    Also handles ``{"data": {"devices": [...]}}``-style nesting.
    """
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("records", "data", "units", "devices", "results", "items"):
        inner = payload.get(key)
        if isinstance(inner, list):
            return inner
    inner_obj = payload.get("data")
    if isinstance(inner_obj, dict):
        for key in ("records", "devices", "units", "items", "results"):
            inner = inner_obj.get(key)
            if isinstance(inner, list):
                return inner
    return []


def _total_pages(payload: _RawJSON) -> int:
    """Return ``total_pages`` from a paginated API envelope, defaulting to 1."""
    if not isinstance(payload, dict):
        return 1
    val = payload.get("total_pages")
    if isinstance(val, int) and val > 1:
        return val
    data = payload.get("data")
    if isinstance(data, dict):
        val2 = data.get("total_pages")
        if isinstance(val2, int) and val2 > 1:
            return val2
    return 1


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
        data = self._request_decoded(
            "PATCH",
            self._device_path(device_id),
            json_body=payload,
        )
        return data if isinstance(data, dict) else {}

    def list_units(self) -> List[Dict[str, Any]]:
        """GET ``/api/v3/units`` — follows pagination and returns all unit dicts."""
        return self._get_all_pages(UNITS_PATH)

    def list_unit_devices(self, unit_id: int) -> List[Dict[str, Any]]:
        """GET ``/api/v3/units/{unit_id}/devices`` — follows pagination."""
        return self._get_all_pages(unit_devices_path(unit_id))

    def _get_all_pages(self, base_path: str) -> List[Dict[str, Any]]:
        """Fetch every page of a paginated list endpoint and return combined rows."""
        all_items: List[Dict[str, Any]] = []
        page = 1
        while True:
            path = f"{base_path}?page={page}"
            raw = self._request_decoded("GET", path, json_body=None)
            items = [x for x in _normalize_list_payload(raw) if isinstance(x, dict)]
            all_items.extend(items)
            if page >= _total_pages(raw):
                break
            page += 1
        return all_items

    def _request_decoded(
        self,
        method: str,
        path: str,
        json_body: Optional[dict],
    ) -> Any:
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

    def _request_json(
        self,
        method: str,
        path: str,
        json_body: Optional[dict],
    ) -> Dict[str, Any]:
        data = self._request_decoded(method, path, json_body)
        return data if isinstance(data, dict) else {}
