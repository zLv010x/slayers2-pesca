import subprocess

import pytest

import shortcut


@pytest.fixture
def project(tmp_path):
    (tmp_path / ".venv" / "Scripts").mkdir(parents=True)
    (tmp_path / ".venv" / "Scripts" / "pythonw.exe").write_bytes(b"")
    (tmp_path / "Iniciar.bat").write_text("@echo off\r\n")
    return tmp_path


@pytest.fixture
def calls(monkeypatch):
    """Troca o PowerShell e o 'ocultar arquivo' por gravadores."""
    rec = {"ps": [], "hidden": []}

    def fake_run(cmd, **kwargs):
        rec["ps"].append(cmd[-1])
        link = rec.get("create")
        if link is not None:
            link.write_bytes(b"lnk")
        return subprocess.CompletedProcess(cmd, rec.get("code", 0), "", rec.get("err", ""))

    monkeypatch.setattr(shortcut.subprocess, "run", fake_run)
    monkeypatch.setattr(shortcut, "_hide", lambda p: rec["hidden"].append(p.name))
    return rec


def test_script_escapes_apostrophe_in_path(tmp_path):
    root = tmp_path / "D'Angelo"
    script = shortcut.ps_script(root / "Iniciar.lnk", root / "pythonw.exe", root / "app.py", root, root / "i.ico")
    assert "D''Angelo" in script
    assert "D'Angelo" not in script.replace("D''Angelo", "")


def test_script_quotes_app_path_with_spaces(tmp_path):
    root = tmp_path / "Anti Virus"
    script = shortcut.ps_script(root / "Iniciar.lnk", root / "pythonw.exe", root / "app.py", root, root / "i.ico")
    assert f"\"{root / 'app.py'}\"" in script
    assert f"{root / 'i.ico'},0" in script


def test_creates_link_and_hides_bat(project, calls):
    calls["create"] = project / shortcut.LINK_NAME
    assert shortcut.ensure(project) is True
    assert len(calls["ps"]) == 1
    assert calls["hidden"] == ["Iniciar.bat"]


def test_existing_link_is_kept_without_powershell(project, calls):
    (project / shortcut.LINK_NAME).write_bytes(b"lnk")
    assert shortcut.ensure(project) is True
    assert calls["ps"] == []
    assert calls["hidden"] == ["Iniciar.bat"]


def test_force_recreates_existing_link(project, calls):
    (project / shortcut.LINK_NAME).write_bytes(b"old")
    calls["create"] = project / shortcut.LINK_NAME
    assert shortcut.ensure(project, force=True) is True
    assert len(calls["ps"]) == 1


def test_without_venv_does_nothing(tmp_path, calls):
    assert shortcut.ensure(tmp_path) is False
    assert calls["ps"] == []
    assert calls["hidden"] == []


def test_powershell_failure_keeps_bat_visible(project, calls):
    calls["code"], calls["err"] = 1, "COM bloqueado"
    assert shortcut.ensure(project) is False
    assert calls["hidden"] == []


def test_powershell_missing_is_not_fatal(project, calls, monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("powershell")
    monkeypatch.setattr(shortcut.subprocess, "run", boom)
    assert shortcut.ensure(project) is False
    assert calls["hidden"] == []
