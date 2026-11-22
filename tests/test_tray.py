"""Tray worker tests do not import GTK, GI or access real ALSA."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ae5ctl.tray import TrayController, TrayUnavailable, run_tray, tray_view


@pytest.fixture
def harness():
    workers = []
    ui_queue = []
    updates = []
    backend = Mock()

    class FakeThread:
        def __init__(self, *, target, daemon, name):
            assert daemon is True
            assert name == "ae5ctl-tray-alsa"
            self.target = target

        def start(self):
            workers.append(self.target)

    controller = TrayController(
        backend,
        lambda state, error, busy: updates.append((state, error, busy)),
        lambda fn: ui_queue.append(fn),
        card="Creative",
        numid=43,
        thread_factory=FakeThread,
    )

    def finish():
        assert workers
        workers.pop(0)()
        assert ui_queue
        assert ui_queue.pop(0)() is False

    return controller, backend, updates, workers, ui_queue, finish


def test_initial_refresh_reads_alsa_without_blocking(harness):
    controller, backend, updates, workers, _, finish = harness
    backend.status.return_value = SimpleNamespace(output="headphones")
    assert controller.request("refresh") is True
    assert updates == [(None, None, True)]
    assert len(workers) == 1
    backend.status.assert_not_called()

    finish()
    backend.status.assert_called_once_with(card="Creative", numid=43)
    assert updates[-1] == ("headphones", None, False)
    assert controller.state == "headphones"


@pytest.mark.parametrize("mode", ["speakers", "headphones"])
def test_switch_and_readback_status(harness, mode):
    controller, backend, updates, _, _, finish = harness
    backend.switch.return_value = SimpleNamespace(after=SimpleNamespace(output=mode))
    assert controller.request(mode) is True
    finish()
    backend.switch.assert_called_once_with(mode, card="Creative", numid=43)
    assert updates[-1] == (mode, None, False)


def test_toggle_uses_backend_readback(harness):
    controller, backend, updates, _, _, finish = harness
    backend.toggle.return_value = SimpleNamespace(
        after=SimpleNamespace(output="speakers")
    )
    assert controller.request("toggle")
    finish()
    backend.toggle.assert_called_once_with(card="Creative", numid=43)
    assert updates[-1] == ("speakers", None, False)


def test_busy_controller_rejects_concurrent_operations(harness):
    controller, backend, updates, workers, _, finish = harness
    backend.status.return_value = SimpleNamespace(output="speakers")
    assert controller.request("refresh")
    assert controller.request("toggle") is False
    assert len(workers) == 1
    finish()
    backend.toggle.assert_not_called()
    assert controller.request("refresh")
    assert updates[-1] == ("speakers", None, True)


def test_failure_reports_error_and_clears_stale_state(harness):
    controller, backend, updates, _, _, finish = harness
    controller.state = "headphones"
    backend.switch.side_effect = RuntimeError("hardware not responding")
    assert controller.request("speakers")
    finish()
    assert updates[-1] == (None, "hardware not responding", False)
    assert controller.state is None
    assert controller.busy is False


def test_close_before_queued_worker_prevents_alsa_access(harness):
    controller, backend, updates, workers, ui_queue, _ = harness
    assert controller.request("speakers")
    controller.close()
    initial = len(updates)

    # No ALSA calls may happen when the queued worker starts after closing.
    workers.pop(0)()
    assert ui_queue == []
    backend.assert_not_called()
    assert controller.closed is True
    assert controller.busy is False
    assert len(updates) == initial
    assert controller.request("toggle") is False


def test_close_during_inflight_read_drops_late_gui_callback(harness):
    controller, backend, updates, workers, ui_queue, _ = harness

    def read(**_kwargs):
        controller.close()
        return SimpleNamespace(output="speakers")

    backend.status.side_effect = read
    assert controller.request("refresh")
    initial = len(updates)
    workers.pop(0)()
    assert len(ui_queue) == 1
    assert ui_queue.pop(0)() is False
    assert len(updates) == initial
    assert controller.closed is True
    assert controller.busy is False


def test_invalid_operation_does_not_start_thread(harness):
    controller, backend, updates, workers, _, _ = harness
    with pytest.raises(ValueError, match="Operación"):
        controller.request("erase-disks")
    assert workers == []
    assert updates == []
    backend.assert_not_called()


def test_tray_reports_missing_desktop_dependency(monkeypatch, capsys):
    def unavailable():
        raise TrayUnavailable("Instale Ayatana")

    monkeypatch.setattr("ae5ctl.tray._load_gui", unavailable)
    assert run_tray() == 4
    assert "Instale Ayatana" in capsys.readouterr().err


def test_discovered_selector_is_cached_and_recovered_after_failure(harness):
    from ae5ctl.alsa import Card, EnumControl, Status

    controller, backend, updates, _, _, finish = harness
    controller.card = None
    controller.numid = None
    status = Status(
        card=Card(7, "Creative", "Sound BlasterX AE-5"),
        control=EnumControl(43, "Output Select", {0: "Speakers", 1: "Headphone"}, (1,)),
        output="headphones",
    )
    backend.status.side_effect = [
        status,
        status,
        RuntimeError("tarjeta desconectada"),
        status,
    ]

    assert controller.request("refresh")
    finish()
    backend.status.assert_called_with(card=None, numid=None)

    assert controller.request("refresh")
    finish()
    backend.status.assert_called_with(card="Creative", numid=43)

    assert controller.request("refresh")
    finish()
    assert updates[-1] == (None, "tarjeta desconectada", False)

    assert controller.request("refresh")
    finish()
    backend.status.assert_called_with(card=None, numid=None)
    assert updates[-1] == ("headphones", None, False)



@pytest.mark.parametrize(
    "state,error,busy,headphones,speakers,toggle,refresh",
    [
        (None, None, True, False, False, False, False),
        (None, None, False, False, False, False, True),
        (None, "Tarjeta desaparecida", False, False, False, False, True),
        ("headphones", None, False, False, True, True, True),
        ("speakers", None, False, True, False, True, True),
        ("speakers", None, True, False, False, False, False),
        ("headphones", "lectura fallida", False, False, False, False, True),
        ("unknown", None, False, False, False, False, True),
    ],
)
def test_tray_actions_require_confirmed_audio_state(
    state, error, busy, headphones, speakers, toggle, refresh
):
    view = tray_view(state, error, busy)
    assert view.headphones_enabled is headphones
    assert view.speakers_enabled is speakers
    assert view.toggle_enabled is toggle
    assert view.refresh_enabled is refresh


def test_tray_error_label_is_single_line_and_untrusted_text_is_bounded():
    view = tray_view(None, "ALSA down\nvalue from device\t" + "x" * 200, False)
    assert view.icon == "audio-card"
    assert view.label.startswith("Error ALSA: ALSA down value from device")
    assert "\n" not in view.label
    assert "\t" not in view.label
    assert len(view.label) <= len("Error ALSA: ") + 100


@pytest.mark.parametrize("reason", [RuntimeError("threads"), OSError("no resources")])
def test_thread_start_failure_clears_busy_and_cached_controls(harness, reason):
    controller, backend, updates, _, _, _ = harness

    class FailingThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise reason

    controller._resolved_card = "Creative"
    controller._resolved_numid = 43
    controller.thread_factory = FailingThread

    assert controller.request("refresh") is False
    assert controller.busy is False
    assert controller.state is None
    assert controller._resolved_card is None
    assert controller._resolved_numid is None
    assert updates[-1] == (None, str(reason), False)
    backend.assert_not_called()


def test_numeric_card_index_pins_detected_id_across_errors(harness):
    from ae5ctl.alsa import Card, EnumControl, Status

    controller, backend, updates, _, _, finish = harness
    controller.card = "7"
    controller.numid = None
    status = Status(
        card=Card(7, "Creative", "Sound BlasterX AE-5"),
        control=EnumControl(
            43, "Output Select", {0: "Speakers", 1: "Headphone"}, (1,)
        ),
        output="headphones",
    )
    backend.status.side_effect = [
        status,
        RuntimeError("Tarjeta desaparecida"),
        status,
    ]

    assert controller.request("refresh")
    finish()
    backend.status.assert_called_with(card="7", numid=None)
    assert controller._pinned_card == "Creative"

    assert controller.request("refresh")
    finish()
    backend.status.assert_called_with(card="Creative", numid=43)
    assert updates[-1] == (None, "Tarjeta desaparecida", False)

    assert controller.request("refresh")
    finish()
    # Do not silently retarget a different device at the old numeric index.
    backend.status.assert_called_with(card="Creative", numid=None)
    assert updates[-1] == ("headphones", None, False)


def test_failed_refresh_recovery_reenables_safe_actions(harness):
    controller, backend, updates, _, _, finish = harness
    backend.status.side_effect = [
        RuntimeError("ALSA fuera de servicio"),
        SimpleNamespace(output="speakers"),
    ]

    assert controller.request("refresh")
    finish()
    assert updates[-1][0] is None
    assert tray_view(*updates[-1]).speakers_enabled is False
    assert tray_view(*updates[-1]).refresh_enabled is True

    assert controller.request("refresh")
    finish()
    assert updates[-1] == ("speakers", None, False)
    assert tray_view(*updates[-1]).headphones_enabled is True
    assert tray_view(*updates[-1]).toggle_enabled is True
