"""Service + setup wizard tests (mocked, cross-platform)."""
import json
from unittest.mock import patch

from owibot.cli import service
from owibot.cli import setup_wizard as wiz


def test_build_bat():
    bat = service.build_bat(r"C:\x\owibot.exe")
    assert "owibot.exe" in bat and "gateway" in bat


def test_build_create_cmd():
    with patch.object(service.shutil, "which", return_value=r"C:\x\owibot.exe"):
        logon = service.build_create_cmd()
        assert "ONLOGON" in logon and "OwiBot-Gateway" in logon
        assert "ONSTART" in service.build_create_cmd(on_start=True)


def test_install_startup_writes_bat(tmp_path):
    with patch.object(service, "bat_path", return_value=tmp_path / "OwiBot-Gateway.bat"), \
         patch.object(service.shutil, "which", return_value=r"C:\x\owibot.exe"), \
         patch.object(service.sys, "platform", "win32"):
        msg = service.install()
        assert "autostart" in msg
        assert (tmp_path / "OwiBot-Gateway.bat").exists()


def test_install_uninstall_status_mocked():
    import subprocess
    ok = subprocess.CompletedProcess(args=[], returncode=0, stdout="SUCCESS", stderr="")
    with patch.object(service.shutil, "which", return_value=r"C:\x\owibot.exe"), \
         patch.object(service.subprocess, "run", return_value=ok):
        if service.sys.platform == "win32":
            assert "logon" in service.install(scheduled=True)
            assert "SUCCESS" in service.uninstall()
            assert "SUCCESS" in service.status()
        else:
            for fn in (lambda: service.install(scheduled=True), service.uninstall, service.status):
                try:
                    fn()
                except RuntimeError as e:
                    assert "Windows-only" in str(e)
                else:
                    raise AssertionError("expected RuntimeError")


def test_parse_allowlist():
    assert wiz.parse_allowlist("@alice, 123 ,") == ["alice", "123"]
    assert wiz.parse_allowlist("") == []


def test_probe_models_mocked():
    payload = json.dumps({"data": [{"id": "m1"}, {"id": "m2"}]}).encode()

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return payload

    with patch.object(wiz.urllib.request, "urlopen", return_value=Resp()):
        assert wiz.probe_models("http://x/v1") == ["m1", "m2"]
    with patch.object(wiz.urllib.request, "urlopen", side_effect=OSError("down")):
        assert wiz.probe_models("http://x/v1") == []


def test_test_chat_mocked():
    payload = json.dumps({"choices": [{"message": {"content": "OK"}}]}).encode()

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return payload

    with patch.object(wiz.urllib.request, "urlopen", return_value=Resp()):
        assert wiz.test_chat("http://x/v1", "k", "m") == "OK"
    with patch.object(wiz.urllib.request, "urlopen", side_effect=OSError("down")):
        try:
            wiz.test_chat("http://x/v1", "k", "m")
        except RuntimeError as e:
            assert "chat test failed" in str(e)
        else:
            raise AssertionError("expected RuntimeError")


def test_check_telegram_mocked():
    payload = json.dumps({"ok": True, "result": {"username": "owibot_agent_bot"}}).encode()

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return payload

    with patch.object(wiz.urllib.request, "urlopen", return_value=Resp()):
        assert wiz.check_telegram("tok") == "@owibot_agent_bot"
    bad = json.dumps({"ok": False, "description": "Unauthorized"}).encode()

    class Resp2(Resp):
        def read(self): return bad

    with patch.object(wiz.urllib.request, "urlopen", return_value=Resp2()):
        try:
            wiz.check_telegram("bad")
        except RuntimeError as e:
            assert "rejected" in str(e)
        else:
            raise AssertionError("expected RuntimeError")
