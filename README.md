# smartrent-devices-homekit

Python service (Raspberry Pi / Debian-friendly) that reads a local `devices.json`, talks to the **SmartRent** HTTP API, and exposes **lights** and **door locks** to Apple **HomeKit** using [HAP-python](https://github.com/ikalchev/HAP-python).

This repo does not ship real device IDs. The client targets the SmartRent **control** API at `control.smartrent.com` (paths and JSON bodies described in the project source and README).

## Requirements

- Python 3.9+
- Network access to `https://control.smartrent.com`
- SmartRent account email and password (`SMARTRENT_EMAIL` / `SMARTRENT_PASSWORD`)

## Install

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install .   # installs the `smartrent_homekit` package from pyproject.toml
```

## Configuration

1. Copy [devices.example.json](devices.example.json) (two lights and one lock) to `devices.json`, or point `SMARTRENT_CONFIG` at a path of your choice. **Replace every `device_id` with your real SmartRent device IDs** from the URL path `.../api/v2/devices/{id}` (e.g. SmartRent resident web app or your own API client). The samples use obvious placeholders like `1000001`. Do not commit real credentials or real device IDs to a public repository.
2. Use the **same** `device_id` for polling (`GET`) and control (`PATCH`) for each device.
3. **Lights**: `type` is `"light"`. Use `"dimmable": true` (default) to expose brightness (0–100%); `false` for on/off only (still uses SmartRent `level` 0 vs 100 in the API).
4. **Locks**: `type` is `"lock"`.

Optional `hap_aid` per device fixes the HomeKit accessory ID across restarts (must be unique per bridged accessory, not `1` or `7`).

## Environment

| Variable | Required | Description |
|----------|----------|-------------|
| `SMARTRENT_EMAIL` | yes | SmartRent login email |
| `SMARTRENT_PASSWORD` | yes | SmartRent login password |
| `SMARTRENT_CONFIG` | no | Path to JSON config (default `./devices.json`; create it by copying a sample file—`devices.json` is gitignored) |
| `SMARTRENT_HAP_PORT` | no | HAP TCP port (default `51827`) |
| `SMARTRENT_HAP_PINCODE` | no | `xxx-xx-xxx` pairing code (default `031-45-154`) |
| `SMARTRENT_HAP_PERSIST` | no | Pairing/crypto persist file (default `~/.smartrent_homekit.state`) |
| `SMARTRENT_LOG_LEVEL` | no | e.g. `DEBUG`, `INFO` |

## Run

```bash
export SMARTRENT_EMAIL='you@example.com'
export SMARTRENT_PASSWORD='your-password'
export SMARTRENT_CONFIG="$PWD/devices.json"
python -m smartrent_homekit
```

On first start, add the bridge in the Home app using the PIN (or install `HAP-python[QRCode]` and use the printed QR).

## Behaviour

- **Auth**: `POST /authentication/sessions` with JSON `{"email","password"}`. Tokens are refreshed when expired (JWT `exp` when present, combined with a 24h rolling fallback) or after HTTP `401` (single retry).
- **Status**: Periodically `GET /api/v2/devices/{id}` for each configured device so HomeKit reflects physical or app-driven changes.
- **Control**: Home app changes call `PATCH /api/v2/devices/{id}` with `{"attributes":[{"name":"level","state":"0-100"}]}` for lights and `{"attributes":[{"name":"locked","state":"true|false"}]}` for locks.

## systemd (Raspberry Pi)

1. Clone this repo under `/home/pi/smartrent-devices-homekit`, create `.venv`, install deps.
2. Install `/etc/default/smartrent-homekit` with your secrets and paths (do not commit):

   ```bash
   SMARTRENT_EMAIL=...
   SMARTRENT_PASSWORD=...
   SMARTRENT_CONFIG=/home/pi/smartrent-devices-homekit/devices.json
   SMARTRENT_HAP_PERSIST=/home/pi/.smartrent_homekit.state
   ```

3. Copy [systemd/smartrent-homekit.service](systemd/smartrent-homekit.service) to `/etc/systemd/system/`, adjust `User`/`paths` if needed.
4. `sudo systemctl daemon-reload && sudo systemctl enable --now smartrent-homekit`
