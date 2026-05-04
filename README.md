# smartrent-devices-homekit

Python service (Raspberry Pi / Debian-friendly) that reads a local `devices.json`, talks to the **SmartRent** HTTP API, and exposes **lights** and **door locks** to Apple **HomeKit** using [HAP-python](https://github.com/ikalchev/HAP-python).

This repo does not ship real device IDs. The client targets the SmartRent **control** API at `control.smartrent.com` (paths and JSON bodies described in the project source and README).

### Project layout

| Area | Package | Role |
|------|---------|------|
| SmartRent HTTP, paths, `devices.json`, setup credentials | [`smartrent_homekit.smartrent`](src/smartrent_homekit/smartrent/) | `SmartRentClient`, `constants`, `config`, `store` |
| HomeKit / HAP-python bridge and accessories | [`smartrent_homekit.homekit`](src/smartrent_homekit/homekit/) | `SmartRentBridge`, light and lock accessories |
| Glue | [`registry.py`](src/smartrent_homekit/registry.py), [`__main__.py`](src/smartrent_homekit/__main__.py), [`cli_setup.py`](src/smartrent_homekit/cli_setup.py) | Wires config + client + HAP; setup wizard |

Splitting **smartrent** and **homekit** keeps API concerns separate from Apple HAP types and polling, while the root package stays a thin composition layer.

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

## Interactive setup (recommended)

The **`smartrent-homekit-setup init`** command opens a **full-screen Textual UI**: sign in (password field shows **one `•` per character** as you type), choose your unit with **arrow keys or the mouse**, then tick lights/locks with **Space or clicks**. It calls `GET /api/v3/units` and `GET /api/v3/units/{unit_id}/devices`, then writes **`devices.json`** and, in the **same directory**, **`smartrent.env`** (mode `0600`) with `SMARTRENT_EMAIL`, `SMARTRENT_PASSWORD`, and `SMARTRENT_CONFIG`. The bridge loads `smartrent.env` automatically when it sits next to the config file you use (including the default `./devices.json`). Use **Ctrl+Q** or **Escape** (on modals) to cancel where shown.

- **Email** and paths are stored in app `config.json` (see below).
- **Password** (and email) live in **`smartrent.env`** next to `devices.json`.

```bash
smartrent-homekit-setup init
# or: python -m smartrent_homekit.cli_setup init
# optional: -o /path/to/devices.json
```

Remove app `config.json` and the recorded **`smartrent.env`** file:

```bash
smartrent-homekit-setup clear-credentials
```

Config directory (from [platformdirs](https://pypi.org/project/platformdirs/) `user_config_dir`): e.g. `~/.config/smartrent-homekit/` on Linux, `~/Library/Application Support/smartrent-homekit/` on macOS. It contains `config.json` (email, last unit id, paths for cleanup).

## Configuration

1. Either use **Interactive setup** above, or copy [devices.example.json](devices.example.json) (two lights and one lock) to `devices.json`, or point `SMARTRENT_CONFIG` at a path of your choice. **Replace every `device_id` with your real SmartRent device IDs** from the URL path `.../api/v2/devices/{id}` (e.g. SmartRent resident web app or your own API client). The samples use obvious placeholders like `1000001`. Do not commit real credentials or real device IDs to a public repository.
2. Use the **same** `device_id` for polling (`GET`) and control (`PATCH`) for each device.
3. **Lights**: `type` is `"light"`. Use `"dimmable": true` (default) to expose brightness (0–100%); `false` for on/off only (still uses SmartRent `level` 0 vs 100 in the API).
4. **Locks**: `type` is `"lock"`.

Optional `hap_aid` per device fixes the HomeKit accessory ID across restarts (must be unique per bridged accessory, not `1` or `7`).

## Environment

| Variable | Required | Description |
|----------|----------|-------------|
| `SMARTRENT_EMAIL` | yes* | SmartRent login email |
| `SMARTRENT_PASSWORD` | yes* | SmartRent login password |
| `SMARTRENT_CONFIG` | no | Path to JSON config (default `./devices.json`; create it by copying a sample file—`devices.json` is gitignored) |

\*If unset, the process reads **`smartrent.env`** beside the resolved `devices.json` path (same directory as `SMARTRENT_CONFIG` or the default file) and applies only missing `SMARTRENT_*` keys.
| `SMARTRENT_HAP_PORT` | no | HAP TCP port (default `51827`) |
| `SMARTRENT_HAP_PINCODE` | no | `xxx-xx-xxx` pairing code (default `031-45-154`) |
| `SMARTRENT_HAP_PERSIST` | no | Pairing/crypto persist file (default `~/.smartrent_homekit.state`) |
| `SMARTRENT_LOG_LEVEL` | no | e.g. `DEBUG`, `INFO` |

## Run

```bash
# Either export manually, or rely on smartrent.env next to devices.json (from init), or:
set -a && . ./smartrent.env && set +a
python -m smartrent_homekit
```

On first start, add the bridge in the Home app using the PIN (or install `HAP-python[QRCode]` and use the printed QR).

## Behaviour

- **Auth**: `POST /authentication/sessions` with JSON `{"email","password"}`. Tokens are refreshed when expired (JWT `exp` when present, combined with a 24h rolling fallback) or after HTTP `401` (single retry).
- **Status**: Periodically `GET /api/v2/devices/{id}` for each configured device so HomeKit reflects physical or app-driven changes.
- **Control**: Home app changes call `PATCH /api/v2/devices/{id}` with `{"attributes":[{"name":"level","state":"0-100"}]}` for lights and `{"attributes":[{"name":"locked","state":"true|false"}]}` for locks.

## systemd (Raspberry Pi)

1. Clone this repo under `/home/pi/smartrent-devices-homekit`, create `.venv`, install deps.
2. Run `smartrent-homekit-setup init` on the Pi (or copy `devices.json` + `smartrent.env` from another machine). For systemd, point **`EnvironmentFile=`** at the env file (same format as `/etc/default/...`):

   ```ini
   EnvironmentFile=-/home/pi/smartrent-devices-homekit/smartrent.env
   ```

   Add other vars there too, e.g. `SMARTRENT_HAP_PERSIST=/home/pi/.smartrent_homekit.state`. Alternatively keep a single `/etc/default/smartrent-homekit` with the same `KEY=value` lines.

3. Copy [systemd/smartrent-homekit.service](systemd/smartrent-homekit.service) to `/etc/systemd/system/`, adjust `User`/`paths`/`EnvironmentFile` if needed.
4. `sudo systemctl daemon-reload && sudo systemctl enable --now smartrent-homekit`
