"""All preview operations are read-only and validate ALSA metadata."""

import json

import pytest

from ae5ctl import cli
from ae5ctl.alsa import AlsaError
from ae5ctl.capabilities import parse_control_detail
from ae5ctl.control_plans import normalize, plan_control


def item(kind, values, *, minimum=0, maximum=100, step=0, items=None):
    return {
        "numid": 7,
        "name": "Test Control",
        "iface": "MIXER",
        "index": 0,
        "device": 0,
        "subdevice": 0,
        "type": kind,
        "values": values,
        "items": items or {},
        "range": {"min": minimum, "max": maximum, "step": step},
        "write_policy": "unverified",
        "driver_reports_writable": True,
    }


@pytest.mark.parametrize(
    "kind,current,wanted,expected",
    [
        ("BOOLEAN", ["off"], "YES", ["on"]),
        ("BOOLEAN", ["1"], "0", ["off"]),
        ("INTEGER", ["10", "10"], "20,80", ["20", "80"]),
        ("INTEGER64", ["0"], "-50", ["-50"]),
    ],
)
def test_valid_numeric_and_boolean_values(kind, current, wanted, expected):
    assert normalize(item(kind, current, minimum=-100, maximum=100), wanted) == expected


@pytest.mark.parametrize("wanted", ["-1", "101", "1.2", "x", "3,4"])
def test_integer_invalid_values(wanted):
    with pytest.raises(AlsaError) as exc:
        normalize(item("INTEGER", ["0"]), wanted)
    assert exc.value.code == "invalid_value"


def test_enumerated_option_indices_and_ambiguous_labels():
    control = item(
        "ENUMERATED", ["0"], items={"0": "Auto", "1": "Headphone", "2": "Speakers"}
    )
    assert normalize(control, "speakers") == ["2"]
    assert normalize(control, "1") == ["1"]
    control["items"]["3"] = "Speakers"
    with pytest.raises(AlsaError) as exc:
        normalize(control, "speakers")
    assert exc.value.code == "ambiguous_value"


def test_step_constraints_and_unsupported_types():
    control = item("INTEGER", ["0"], minimum=0, maximum=30, step=5)
    assert normalize(control, "15") == ["15"]
    with pytest.raises(AlsaError, match="Incremento"):
        normalize(control, "13")
    with pytest.raises(AlsaError) as exc:
        normalize(item("IEC958", ["0"]), "1")
    assert exc.value.code == "unsupported_type"


def test_header_semantic_coordinates_default_and_explicit():
    response = """numid=7,iface=MIXER,name='Test Control',index=2,device=4,subdevice=1
  ; type=BOOLEAN,access=rw------,values=1
  : values=off
"""
    control = parse_control_detail(response, 7)
    assert (control["index"], control["device"], control["subdevice"]) == (2, 4, 1)


@pytest.fixture
def model(monkeypatch):
    from ae5ctl import control_plans

    backend = object()
    report = {
        "ok": True,
        "card": {"id": "Creative", "index": 7, "name": "AE-5"},
        "controls": [item("INTEGER", ["40", "40"])],
        "errors": [],
    }
    calls = []

    def scan(instance, **kwargs):
        assert instance is backend
        calls.append(kwargs)
        return report

    monkeypatch.setattr(control_plans, "scan_capabilities", scan)
    return backend, report, calls


def test_plan_includes_semantic_identity_and_never_permits_write(model):
    backend, report, calls = model
    result = plan_control(backend, card="Creative", numid=7, requested="50,50")
    assert result["previous_values"] == ["40", "40"]
    assert result["requested_values"] == ["50", "50"]
    assert result["identity"]["card_id"] == "Creative"
    assert result["can_apply"] is False
    assert result["changed"] is True
    assert "command" not in result
    assert calls == [{"card": "Creative", "numid": 7}]
    report["controls"][0]["write_policy"] = "blocked"
    assert (
        plan_control(backend, card=None, numid=7, requested="40,40")["can_apply"]
        is False
    )


def test_report_error_fails_closed(model):
    backend, report, _ = model
    report["errors"] = [{"code": "command_failed", "message": "unavailable"}]
    with pytest.raises(AlsaError) as exc:
        plan_control(backend, card=None, numid=7, requested="5,5")
    assert exc.value.code == "command_failed"


def test_cli_plan_returns_only_a_preview(monkeypatch, capsys, model):
    backend, _report, _ = model
    monkeypatch.setattr(cli, "AlsaBackend", lambda **kwargs: backend)
    assert cli.main(["controls", "plan", "7", "70,80", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["requested_values"] == ["70", "80"]
    assert data["scope"] == "alsa_control_plan"
    assert data["can_apply"] is False


def test_cli_invalid_values_fail_explicitly(monkeypatch, capsys, model):
    backend, _report, _ = model
    monkeypatch.setattr(cli, "AlsaBackend", lambda **kwargs: backend)
    assert cli.main(["controls", "plan", "7", "101,101", "--json"]) == 3
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "invalid_value"


def test_plan_contains_full_control_contract_for_future_stale_guards(model):
    from ae5ctl.control_plans import fingerprint

    backend, _report, _ = model
    plan = plan_control(backend, card="Creative", numid=7, requested="50,50")
    assert plan["contract"]["identity"]["name"] == "Test Control"
    assert plan["contract"]["value_count"] == 2
    assert plan["contract_fingerprint"] == fingerprint(plan["contract"])
    assert len(plan["contract_fingerprint"]) == 64
