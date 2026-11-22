"""Optional GTK/Ayatana tray that never runs ALSA commands on GTK's main loop."""

import sys
from threading import Lock, Thread
from typing import Callable

from ae5ctl.alsa import AlsaBackend


class TrayController:
    """Testable asynchronous bridge between the ALSA backend and a GUI."""

    OPERATIONS = {"refresh", "headphones", "speakers", "toggle"}

    def __init__(
        self,
        backend: AlsaBackend,
        on_update: Callable[[str | None, str | None, bool], None],
        dispatch: Callable[[Callable[[], bool]], object],
        *,
        card: str | None = None,
        numid: int | None = None,
        thread_factory: Callable[..., Thread] = Thread,
    ):
        self.backend = backend
        self.on_update = on_update
        self.dispatch = dispatch
        self.card = card
        self.numid = numid
        self.thread_factory = thread_factory
        self.state: str | None = None
        self.busy = False
        self.closed = False
        self._lock = Lock()

    def request(self, operation: str) -> bool:
        """Reject overlapping requests and execute the backend in a worker."""
        if operation not in self.OPERATIONS:
            raise ValueError(f"Operación no válida: {operation}")
        with self._lock:
            if self.busy or self.closed:
                return False
            self.busy = True
        self.on_update(self.state, None, True)

        def worker() -> None:
            state: str | None = None
            error: str | None = None
            try:
                options = {"card": self.card, "numid": self.numid}
                if operation == "refresh":
                    state = self.backend.status(**options).output
                elif operation == "toggle":
                    state = self.backend.toggle(**options).after.output
                else:
                    state = self.backend.switch(operation, **options).after.output
            except Exception as exc:
                # GUI thread boundaries must not leave the menu permanently busy.
                error = str(exc) or type(exc).__name__

            def finish() -> bool:
                with self._lock:
                    if self.closed:
                        return False
                    self.state = state
                    self.busy = False
                self.on_update(state, error, False)
                return False

            self.dispatch(finish)

        try:
            self.thread_factory(
                target=worker, daemon=True, name="ae5ctl-tray-alsa"
            ).start()
        except RuntimeError as exc:
            with self._lock:
                self.busy = False
                self.state = None
            self.on_update(None, str(exc), False)
            return False
        return True

    def close(self) -> None:
        with self._lock:
            self.closed = True


class TrayUnavailable(RuntimeError):
    """The desktop bindings or session are unavailable."""


def _load_gui():
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import AyatanaAppIndicator3, GLib, Gtk
    except (ImportError, RuntimeError, ValueError) as exc:
        raise TrayUnavailable(
            "La bandeja necesita python3-gi, gir1.2-gtk-3.0 y "
            "gir1.2-ayatanaappindicator3-0.1. "
            "Instálelos mediante apt y use el Python del sistema "
            "(o un venv con --system-site-packages)."
        ) from exc
    return Gtk, GLib, AyatanaAppIndicator3


def run_tray(
    *,
    card: str | None = None,
    numid: int | None = None,
    timeout: float = 3.0,
    interval: int = 5,
) -> int:
    """Launch the optional desktop indicator; CLI imports remain headless."""
    try:
        Gtk, GLib, AppIndicator = _load_gui()
        initialized = Gtk.init_check()
        ready = initialized[0] if isinstance(initialized, tuple) else initialized
        if not ready:
            raise TrayUnavailable(
                "No hay sesión gráfica GTK disponible. Inicie sesión en el escritorio."
            )
    except (TrayUnavailable, RuntimeError) as exc:
        print(f"Error de bandeja: {exc}", file=sys.stderr)
        return 4

    indicator = AppIndicator.Indicator.new(
        "ae5ctl.audio",
        "audio-card",
        AppIndicator.IndicatorCategory.SYSTEM_SERVICES,
    )
    menu = Gtk.Menu()
    status_item = Gtk.MenuItem(label="Salida ALSA: consultando...")
    status_item.set_sensitive(False)
    menu.append(status_item)
    menu.append(Gtk.SeparatorMenuItem())

    headphones = Gtk.MenuItem(label="🎧 Auriculares")
    speakers = Gtk.MenuItem(label="🔊 Altavoces")
    toggle = Gtk.MenuItem(label="Alternar auriculares / altavoces")
    refresh = Gtk.MenuItem(label="Actualizar estado")
    for item in (headphones, speakers, toggle, refresh):
        menu.append(item)
    menu.append(Gtk.SeparatorMenuItem())
    quit_item = Gtk.MenuItem(label="Salir")
    menu.append(quit_item)

    def update(state: str | None, error: str | None, busy: bool) -> None:
        icons = {"headphones": "audio-headphones", "speakers": "audio-speakers"}
        icon = icons.get(state, "audio-card")
        indicator.set_icon_full(icon, "AE-5")
        if error is not None:
            status_item.set_label(f"Error ALSA: {error[:100]}")
        elif busy:
            status_item.set_label("AE-5: consultando...")
        else:
            names = {"headphones": "auriculares", "speakers": "altavoces"}
            status_item.set_label(
                f"Salida ALSA: {names.get(state, 'desconocida')}"
            )
        headphones.set_sensitive(not busy and state != "headphones")
        speakers.set_sensitive(not busy and state != "speakers")
        toggle.set_sensitive(not busy and state is not None)
        refresh.set_sensitive(not busy)

    controller = TrayController(
        AlsaBackend(timeout=timeout),
        update,
        lambda callback: GLib.idle_add(callback),
        card=card,
        numid=numid,
    )
    headphones.connect("activate", lambda *_: controller.request("headphones"))
    speakers.connect("activate", lambda *_: controller.request("speakers"))
    toggle.connect("activate", lambda *_: controller.request("toggle"))
    refresh.connect("activate", lambda *_: controller.request("refresh"))

    def quit_app(*_args) -> None:
        controller.close()
        Gtk.main_quit()

    quit_item.connect("activate", quit_app)
    update(None, None, True)
    menu.show_all()
    indicator.set_menu(menu)
    indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
    if hasattr(indicator, "set_secondary_activate_target"):
        indicator.set_secondary_activate_target(toggle)

    def poll() -> bool:
        if controller.closed:
            return False
        controller.request("refresh")
        return True

    controller.request("refresh")
    GLib.timeout_add_seconds(interval, poll)
    try:
        Gtk.main()
    finally:
        controller.close()
    return 0
