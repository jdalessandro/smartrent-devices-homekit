"""
SmartRent control API surface used by this package.

- POST https://control.smartrent.com/authentication/sessions — JSON `email` / `password`
- GET  https://control.smartrent.com/api/v2/devices/{id} — device state (attributes array)
- PATCH https://control.smartrent.com/api/v2/devices/{id} — JSON `{"attributes":[...]}`

Set each `device_id` in `devices.json` to the numeric id from the same path segment on
`control.smartrent.com` (use the same id for GET polling and PATCH control).
"""

CONTROL_BASE = "https://control.smartrent.com"
SESSIONS_PATH = "/authentication/sessions"
DEVICES_API_PREFIX = "/api/v2/devices"

# Rolling 24h upper bound on session reuse when JWT `exp` is absent or very long.
TOKEN_FALLBACK_TTL_MS = 24 * 60 * 60 * 1000

# Optional headers commonly accepted by the control API for session creation.
AUTH_EXTRA_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "X-AppVersion": "chrome-resweb-147.0.0",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
    ),
}
