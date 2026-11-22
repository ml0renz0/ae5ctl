"""Tray worker tests do not import GTK, GI or access real ALSA."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ae5ctl.tray import TrayController, TrayUnavailable, run_tray


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


def test_shutdown_ignores_late_callbacks(harness):
    controller, backend, updates, workers, ui_queue, _ = harness
    backend.status.return_value = SimpleNamespace(output="speakers")
    assert controller.request("refresh")
    controller.close()
    initial = len(updates)
    assert controller.request("toggle") is False
    assert len(ui_queue) == 0

    # The in-flight worker may return after the user closes the tray.
    workers.pop(0)()
    assert len(ui_queue) == 1
    assert ui_queue.pop(0)() is False
    assert controller.closed is True
    assert len(updates) == initial
    backend.toggle.assert_not_called()


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
