"""Textual (TUI) setup wizard: mouse + keyboard, masked password preview."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Input,
    Label,
    ListItem,
    ListView,
    LoadingIndicator,
    Static,
)

from smartrent_homekit.smartrent.client import SmartRentClient
from smartrent_homekit.smartrent.store import (
    CREDENTIALS_ENV_FILENAME,
    get_last_unit_id,
    get_saved_email,
    save_credentials_env_path,
    save_email,
    save_last_unit_id,
    write_credentials_env_file,
)
from smartrent_homekit.wizard_common import (
    device_row_label,
    device_summaries_list,
    unit_rows,
)

log = logging.getLogger(__name__)

LoginResult = Union[Tuple[str, str], None]
DevicePickResult = Union[Tuple[List[Dict[str, Any]], float], None]


class LoginScreen(ModalScreen[LoginResult]):
    """Email + password (each typed char shown as •)."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=True)]

    DEFAULT_CSS = """
    LoginScreen {
        align: center middle;
    }
    LoginScreen > Vertical {
        width: 76;
        max-width: 100%;
        height: auto;
        border: tall $accent;
        background: $surface;
        padding: 1 2;
    }
    LoginScreen Static.hint {
        margin-top: 0;
        margin-bottom: 1;
    }
    LoginScreen Label.field-label {
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Sign in with your SmartRent account.")
            yield Label("Email", classes="field-label")
            yield Input(
                placeholder="you@example.com",
                id="email",
                value=get_saved_email() or "",
            )
            yield Label("Password (• matches each character)", classes="field-label")
            yield Input(placeholder="", password=True, id="password")
            yield Static(
                "Tip: click fields or Tab between them. ↑/↓ move inside lists later.",
                classes="hint muted",
            )
            with Horizontal(classes="buttons"):
                yield Button("Sign in", variant="primary", id="login_go")
                yield Button("Cancel", id="login_cancel")

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#login_cancel")
    def cancel_pressed(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#login_go")
    def sign_in_pressed(self) -> None:
        email = self.query_one("#email", Input).value.strip()
        password = self.query_one("#password", Input).value
        if not email or not password:
            self.notify("Enter email and password.", severity="error")
            return
        self.dismiss((email, password))


class UnitPickerScreen(ModalScreen[Optional[int]]):
    """Pick a unit: arrows, Enter, or mouse."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=True)]

    DEFAULT_CSS = """
    UnitPickerScreen {
        align: center middle;
    }
    UnitPickerScreen > Vertical {
        width: 88;
        max-width: 100%;
        height: 80%;
        border: tall $accent;
        background: $surface;
        padding: 1 2;
    }
    UnitPickerScreen ListView {
        height: 1fr;
        min-height: 6;
        border: solid $border;
    }
    """

    def __init__(self, client: SmartRentClient) -> None:
        super().__init__()
        self.client = client
        self.rows: List[Tuple[int, str]] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Choose your unit — ↑/↓ or click a row, then Continue.")
            with Vertical(id="unit_slot"):
                yield LoadingIndicator(id="unit_loading")
            with Horizontal(classes="buttons"):
                yield Button(
                    "Continue",
                    variant="primary",
                    id="unit_ok",
                    disabled=True,
                )
                yield Button("Cancel", id="unit_cancel")

    def on_mount(self) -> None:
        self._load_units()

    @work(exclusive=True)
    async def _load_units(self) -> None:
        try:
            units = await asyncio.to_thread(self.client.list_units)
        except Exception as e:
            log.exception("list_units failed")
            self._fail_units(str(e))
            return
        self.rows = unit_rows(units)
        if not self.rows:
            self.notify("No units in this account.", severity="warning", timeout=8)
            self.dismiss(None)
            return
        await self.query_one("#unit_loading", LoadingIndicator).remove()
        last = get_last_unit_id()
        init_i = 0
        if last is not None:
            for j, (uid, _) in enumerate(self.rows):
                if uid == last:
                    init_i = j
                    break
        items = [
            ListItem(Label(f"{label}   (unit id {uid})"))
            for uid, label in self.rows
        ]
        slot = self.query_one("#unit_slot", Vertical)
        await slot.mount(
            ListView(*items, id="unit_list", initial_index=init_i),
        )
        self.query_one("#unit_ok", Button).disabled = False

    def _fail_units(self, message: str) -> None:
        self.notify(message, severity="error", timeout=12)
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#unit_cancel")
    def unit_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#unit_ok")
    def unit_ok(self) -> None:
        lv = self.query_one("#unit_list", ListView)
        if lv.index is None or not self.rows:
            self.notify("Select a unit from the list.", severity="error")
            return
        uid = self.rows[lv.index][0]
        save_last_unit_id(uid)
        self.dismiss(uid)


class DevicePickerScreen(ModalScreen[DevicePickResult]):
    """
    Pick devices for HomeKit.

    Each supported row is a ``ListItem``; press **Enter** or **click** to toggle
    it selected (shows ✓).  Unsupported rows are rendered as disabled ListItems
    and cannot be selected.  Navigate with ↑/↓ or the mouse.
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=True)]

    DEFAULT_CSS = """
    DevicePickerScreen {
        align: center middle;
    }
    DevicePickerScreen > Vertical {
        width: 100%;
        max-width: 110;
        height: 85%;
        border: tall $accent;
        background: $surface;
    }
    DevicePickerScreen #dev_instruction {
        padding: 1 2 0 2;
    }
    DevicePickerScreen ListView {
        height: 1fr;
        margin: 0 1;
        border: solid $border;
    }
    DevicePickerScreen #dev_footer {
        height: auto;
        padding: 1 2 1 2;
    }
    DevicePickerScreen #dev_footer Label {
        margin-bottom: 1;
    }
    DevicePickerScreen #dev_footer Horizontal {
        height: 3;
        margin-top: 1;
    }
    DevicePickerScreen #dev_footer Button {
        min-width: 14;
        height: 3;
    }
    """

    def __init__(self, summaries: List[Optional[Dict[str, Any]]]) -> None:
        super().__init__()
        self.summaries = summaries
        self._selected: set = set()

    def _item_label(self, i: int) -> str:
        check = "✓" if i in self._selected else " "
        return f"[{check}]  {device_row_label(i, self.summaries[i])}"

    def compose(self) -> ComposeResult:
        items = []
        for i, summ in enumerate(self.summaries):
            supported = summ is not None and summ.get("role") is not None
            items.append(
                ListItem(
                    Label(self._item_label(i)),
                    id=f"dev_item_{i}",
                    disabled=not supported,
                )
            )
        with Vertical():
            yield Label(
                "Include lights & locks — Enter or click a row to toggle (✓). ↑/↓ to navigate.",
                id="dev_instruction",
            )
            yield ListView(*items, id="dev_list")
            with Vertical(id="dev_footer"):
                yield Label("Poll interval (seconds)")
                yield Input(value="10", id="poll_interval", type="integer")
                with Horizontal():
                    yield Button("Save", variant="primary", id="dev_save")
                    yield Button("Cancel", id="dev_cancel")

    def _toggle(self, index: int) -> None:
        summ = self.summaries[index]
        if summ is None or summ.get("role") is None:
            return
        if index in self._selected:
            self._selected.discard(index)
        else:
            self._selected.add(index)
        item = self.query_one(f"#dev_item_{index}", ListItem)
        item.query_one(Label).update(self._item_label(index))

    @on(ListView.Selected, "#dev_list")
    def row_selected(self, event: ListView.Selected) -> None:
        self._toggle(event.index)

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#dev_cancel")
    def dev_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#dev_save")
    def dev_save(self) -> None:
        picked = [
            self.summaries[i]
            for i in sorted(self._selected)
            if self.summaries[i] is not None and self.summaries[i].get("role")  # type: ignore[union-attr]
        ]
        if not picked:
            self.notify("Select at least one light or lock.", severity="error")
            return
        raw_poll = self.query_one("#poll_interval", Input).value.strip()
        try:
            poll_interval = float(raw_poll)
        except ValueError:
            poll_interval = 10.0
        self.dismiss((picked, poll_interval))


class DoneScreen(ModalScreen[None]):
    """Summary after files are written."""

    BINDINGS = [Binding("escape", "close", "Close", show=True)]

    DEFAULT_CSS = """
    DoneScreen {
        align: center middle;
    }
    DoneScreen > Vertical {
        width: 88;
        max-width: 100%;
        height: auto;
        border: tall $success;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(self, devices_path: Path, env_path: Path, n_devices: int) -> None:
        super().__init__()
        self.devices_path = devices_path
        self.env_path = env_path
        self.n_devices = n_devices

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Done", classes="title")
            yield Static(f"Wrote {self.n_devices} device(s) to:")
            yield Static(str(self.devices_path), classes="path")
            yield Static(f"Credentials ({CREDENTIALS_ENV_FILENAME}):")
            yield Static(str(self.env_path), classes="path")
            yield Button("Close", variant="primary", id="done_close")

    def action_close(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#done_close")
    def close_pressed(self) -> None:
        self.dismiss(None)


def _write_artifacts(
    output: Path,
    email: str,
    password: str,
    picked: List[Dict[str, Any]],
    poll_interval: float,
) -> Tuple[Path, Path]:
    out_doc: Dict[str, Any] = {
        "poll_interval_seconds": poll_interval,
        "devices": [],
    }
    for summ in picked:
        entry: Dict[str, Any] = {
            "name": summ["name"],
            "type": summ["role"],
            "device_id": summ["id"],
        }
        if summ["role"] == "light":
            entry["dimmable"] = summ["dimmable"]
        out_doc["devices"].append(entry)

    output.parent.mkdir(parents=True, exist_ok=True)
    resolved_out = output.resolve()
    output.write_text(json.dumps(out_doc, indent=2) + "\n", encoding="utf-8")
    try:
        output.chmod(0o600)
    except OSError:
        pass

    env_path = write_credentials_env_file(resolved_out, email, password)
    save_credentials_env_path(env_path)
    save_email(email)
    return resolved_out, env_path


class SetupApp(App[None]):
    """Orchestrates login → unit → devices → write files."""

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=True),
    ]
    CSS = """
    Screen .title {
        text-style: bold;
        margin-bottom: 1;
    }
    Screen .path {
        color: $accent;
        margin-bottom: 1;
    }
    Screen .muted {
        color: $text-muted;
    }
    Screen Horizontal.buttons {
        height: 3;
        margin-top: 1;
    }
    Screen Horizontal.buttons Button {
        min-width: 14;
    }
    """

    def __init__(self, output_path: Path) -> None:
        super().__init__()
        self.output_path = output_path
        self._client: Optional[SmartRentClient] = None

    def compose(self) -> ComposeResult:
        yield Footer()

    def on_mount(self) -> None:
        # Textual requires ``push_screen_wait`` to run inside an active worker.
        self.run_worker(self._run_setup_flow, exclusive=True)

    async def _run_setup_flow(self) -> None:
        creds = await self.push_screen_wait(LoginScreen())
        if creds is None:
            self.exit(return_code=1)
            return
        email, password = creds
        self._client = SmartRentClient(email=email, password=password)
        try:
            await asyncio.to_thread(self._client.refresh_token)
        except Exception as e:
            log.exception("Login failed")
            self.notify(f"Login failed: {e}", severity="error", timeout=12)
            self._client.close()
            self._client = None
            self.exit(return_code=1)
            return

        assert self._client is not None
        unit_id = await self.push_screen_wait(UnitPickerScreen(self._client))
        if unit_id is None:
            self._client.close()
            self._client = None
            self.exit(return_code=1)
            return

        try:
            devices = await asyncio.to_thread(
                self._client.list_unit_devices,
                unit_id,
            )
        except Exception as e:
            log.exception("list_unit_devices failed")
            self.notify(str(e), severity="error", timeout=12)
            self._client.close()
            self._client = None
            self.exit(return_code=1)
            return

        summaries = device_summaries_list(devices)
        picked_result = await self.push_screen_wait(DevicePickerScreen(summaries))
        if picked_result is None:
            self._client.close()
            self._client = None
            self.exit(return_code=1)
            return

        picked, poll_interval = picked_result
        try:
            resolved_out, env_path = _write_artifacts(
                self.output_path,
                email,
                password,
                picked,
                poll_interval,
            )
        except OSError as e:
            self.notify(f"Could not write files: {e}", severity="error", timeout=12)
            self._client.close()
            self._client = None
            self.exit(return_code=1)
            return

        await self.push_screen_wait(
            DoneScreen(resolved_out, env_path, len(picked)),
        )
        self._client.close()
        self._client = None
        self.exit(return_code=0)


def run_setup_wizard(output: Path) -> int:
    """
    Run the full-screen Textual wizard.

    :param output: Path for ``devices.json`` (``smartrent.env`` is written beside it).
    :returns: Process exit code (0 success, 1 cancelled or error).
    """
    logging.basicConfig(level=logging.WARNING)
    app = SetupApp(output_path=output)
    app.run(inline=False)
    return int(app.return_code or 0)
