"""Versioned user presets: strict JSON, semantic matching, and no ALSA writes."""

import json
import os

import pytest

from ae5ctl import cli
from ae5ctl import preset_store as presets
from ae5ctl.preset_store import (
    PresetError,
    PresetStore,
    compare,
    new_preset,
    remove_control,
    set_control,
    validate,
)


def control(
    name="Master Playback Volume",
    kind="INTEGER",
    values=None,
    *,
    numid=11,
    policy="unverified",
):
    if values is None:
        values = ["40", "40"]
    return {
        "numid": numid,
        "name": name,
        "iface": "MIXER",
        "index": 0,
        "device": 0,
        "subdevice": 0,
        "type": kind,
        "access": "rw------",
        "driver_reports_writable": True,
        "values": values,
        "items": {"0": "Headphone", "1": "Speakers"} if kind == "ENUMERATED" else {},
        "range": {"min": 0, "max": 100, "step": 1} if kind == "INTEGER" else {},
        "family": "routing" if kind == "ENUMERATED" else "levels",
        "write_policy": policy,
        "editable_by_ae5ctl": False,
    }


@pytest.fixture
def simulated(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    backend = object()
    selected = [
        control(),
        control("Output Select", "ENUMERATED", ["1"], numid=43),
    ]
    calls = []

    def scan(obj, *, card=None, numid=None):
        assert obj is backend
        assert card == "Creative"
        calls.append(numid)
        found = [item for item in selected if numid is None or item["numid"] == numid]
        return {
            "ok": bool(found),
            "card": {"id": "Creative", "index": 7, "name": "AE-5"},
            "controls": found,
            "errors": [] if found else [
                {"code": "no_control", "message": "No existe el control."}
            ],
        }

    monkeypatch.setattr(presets, "scan_capabilities", scan)
    monkeypatch.setattr(cli, "AlsaBackend", lambda **_: backend)
    return PresetStore(), selected, calls


def test_create_read_list_and_delete_do_not_need_hardware(tmp_path, simulated, capsys):
    store, _controls, calls = simulated
    assert cli.main(["presets", "create", "gaming", "--card", "Creative", "--json"]) == 0
    path = store.root / "gaming.json"
    assert path.is_file()
    assert path.stat().st_mode & 0o777 == 0o600
    doc = json.loads(capsys.readouterr().out)
    assert doc == new_preset("gaming", "Creative")
    assert cli.main(["presets", "list", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["presets"][0]["name"] == "gaming"
    assert cli.main(["presets", "show", "gaming", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == doc
    assert cli.main(["presets", "delete", "gaming", "--json"]) == 0
    assert not path.exists()
    assert calls == []


def test_capture_selected_controls_as_semantic_fields(simulated, capsys):
    store, controls, calls = simulated
    assert cli.main(
        ["presets", "capture", "music", "--card", "Creative",
         "--numid", "11", "--numid", "43", "--json"]
    ) == 0
    doc = json.loads(capsys.readouterr().out)
    assert len(doc["controls"]) == 2
    assert all("numid" not in entry for entry in doc["controls"])
    assert all("numid" not in entry["identity"] for entry in doc["controls"])
    by_name = {entry["identity"]["name"]: entry for entry in doc["controls"]}
    assert by_name["Output Select"]["values"] == ["Speakers"]
    assert by_name["Master Playback Volume"]["values"] == ["40", "40"]
    assert store.read("music") == doc
    assert calls == [11, 43]
    assert controls[0]["values"] == ["40", "40"]


def test_set_updates_values_and_diff_reads_but_does_not_write(simulated, capsys):
    _store, controls, calls = simulated
    assert cli.main(["presets", "create", "gaming", "--card", "Creative"]) == 0
    capsys.readouterr()
    assert cli.main(
        ["presets", "set", "gaming", "--numid", "11", "--values", "70,70", "--json"]
    ) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["controls"][0]["values"] == ["70", "70"]
    assert cli.main(["presets", "diff", "gaming", "--json"]) == 0
    diff = json.loads(capsys.readouterr().out)
    assert diff["scope"] == "alsa_preset_diff"
    assert diff["summary"] == {"total": 1, "same": 0, "different": 1, "unavailable": 0}
    assert diff["can_apply"] is False
    assert diff["controls"][0]["status"] == "different"
    assert controls[0]["values"] == ["40", "40"]
    assert calls == [11, None]


def test_remove_semantic_control_and_export_import_roundtrip(simulated, tmp_path, capsys):
    store, _controls, _calls = simulated
    assert cli.main(
        ["presets", "capture", "music", "--card", "Creative",
         "--numid", "11", "--numid", "43"]
    ) == 0
    capsys.readouterr()
    assert cli.main(
        ["presets", "remove", "music", "--control", "Output Select", "--json"]
    ) == 0
    doc = json.loads(capsys.readouterr().out)
    assert len(doc["controls"]) == 1
    exported = tmp_path / "music-export.json"
    assert cli.main(["presets", "export", "music", str(exported)]) == 0
    capsys.readouterr()
    store.delete("music")
    assert cli.main(["presets", "import", str(exported), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == doc
    assert store.read("music") == doc


def test_missing_control_is_reported_as_incompatible(simulated, capsys):
    _store, controls, _calls = simulated
    assert cli.main(
        ["presets", "capture", "game", "--card", "Creative", "--numid", "11"]
    ) == 0
    capsys.readouterr()
    controls.clear()
    assert cli.main(["presets", "diff", "game", "--json"]) == 0
    diff = json.loads(capsys.readouterr().out)
    assert diff["compatible"] is False
    assert diff["controls"][0]["status"] == "missing"


def test_blocked_driver_control_is_never_marked_write_ready(simulated, capsys):
    _store, controls, _calls = simulated
    assert cli.main(
        ["presets", "capture", "game", "--card", "Creative", "--numid", "11"]
    ) == 0
    capsys.readouterr()
    controls[0]["write_policy"] = "blocked"
    assert cli.main(["presets", "diff", "game", "--json"]) == 0
    diff = json.loads(capsys.readouterr().out)
    assert diff["controls"][0]["status"] == "restricted"
    assert diff["compatible"] is False
    assert diff["can_apply"] is False


def test_duplicate_numid_capture_rejected_before_io(simulated, capsys):
    store, _controls, calls = simulated
    assert cli.main(
        ["presets", "capture", "oops", "--card", "Creative", "--numid", "11",
         "--numid", "11", "--json"]
    ) == 4
    result = json.loads(capsys.readouterr().out)
    assert result["error"]["code"] == "duplicate_control"
    assert calls == []
    assert not (store.root / "oops.json").exists()


def test_import_rejects_unknown_fields_and_duplicate_keys(tmp_path):
    store = PresetStore(tmp_path / "presets")
    source = tmp_path / "untrusted.json"
    doc = new_preset("good", "Creative")
    doc["run_shell"] = "evil"
    source.write_text(json.dumps(doc))
    with pytest.raises(PresetError) as exc:
        store.import_file(source)
    assert exc.value.code == "invalid_preset"
    source.write_text(
        '{"schema_version":1,"name":"good","name":"bad",'
        '"card_id":"Creative","controls":[]}'
    )
    with pytest.raises(PresetError) as exc:
        store.import_file(source)
    assert exc.value.code == "duplicate_json_key"


@pytest.mark.parametrize("name", ["../outside", "a/b", ".secret", "", "a" * 49])
def test_unsafe_preset_names_cannot_escape_directory(tmp_path, name):
    store = PresetStore(tmp_path / "private")
    with pytest.raises(PresetError) as exc:
        store.save(new_preset(name, "Creative"))
    assert exc.value.code == "invalid_name"
    assert not store.root.exists()


def test_duplicate_semantic_controls_and_malformed_types_are_rejected():
    doc = new_preset("gaming", "Creative")
    identity = {
        "iface": "MIXER", "name": "Volume",
        "index": 0, "device": 0, "subdevice": 0,
    }
    entry = {"identity": identity, "type": "INTEGER", "values": ["10"]}
    doc["controls"] = [entry, dict(entry)]
    with pytest.raises(PresetError) as exc:
        validate(doc)
    assert exc.value.code == "duplicate_control"
    doc["controls"] = [{**entry, "type": []}]
    with pytest.raises(PresetError) as exc:
        validate(doc)
    assert exc.value.code == "unsupported_type"


def test_import_and_export_require_force_for_existing_destination(tmp_path):
    store = PresetStore(tmp_path / "presets")
    store.save(new_preset("music", "Creative"))
    export = tmp_path / "export.json"
    store.export_file("music", export)
    with pytest.raises(PresetError) as exc:
        store.export_file("music", export)
    assert exc.value.code == "already_exists"
    store.export_file("music", export, overwrite=True)
    with pytest.raises(PresetError) as exc:
        store.import_file(export)
    assert exc.value.code == "already_exists"
    store.import_file(export, overwrite=True)


def test_symlinks_rejected_on_import_and_store_directory(tmp_path):
    root = tmp_path / "actual"
    root.mkdir()
    store = PresetStore(root)
    store.save(new_preset("game", "Creative"))
    evil = tmp_path / "link.json"
    evil.symlink_to(root / "game.json")
    with pytest.raises(PresetError) as exc:
        store.import_file(evil)
    assert exc.value.code == "file_missing"
    other = PresetStore(tmp_path / "linked")
    other.root.symlink_to(root, target_is_directory=True)
    with pytest.raises(PresetError) as exc:
        other.list()
    assert exc.value.code == "unsafe_directory"


def test_remove_ambiguous_name_fails_instead_of_guessing():
    doc = new_preset("game", "Creative")
    first = {
        "identity": {"iface": "MIXER", "name": "Volume",
                     "index": 0, "device": 0, "subdevice": 0},
        "type": "INTEGER", "values": ["20"],
    }
    second = {
        **first,
        "identity": {**first["identity"], "index": 1},
    }
    set_control(doc, first)
    set_control(doc, second)
    with pytest.raises(PresetError) as exc:
        remove_control(doc, "Volume")
    assert exc.value.code == "ambiguous_control"


def test_preset_cli_has_no_apply_subcommand():
    parser = cli.parser()
    with pytest.raises(SystemExit) as error:
        parser.parse_args(["presets", "apply", "gaming"])
    assert error.value.code == 2


def test_presets_store_files_are_0600_even_with_permissive_umask(tmp_path):
    store = PresetStore(tmp_path / "private")
    before = os.umask(0)
    try:
        store.save(new_preset("gaming", "Creative"))
    finally:
        os.umask(before)
    assert (store.root / "gaming.json").stat().st_mode & 0o777 == 0o600
