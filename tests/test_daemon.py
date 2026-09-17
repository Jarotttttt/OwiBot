"""Background daemon tests (mocked spawn/kill)."""
from unittest.mock import patch

from owibot.cli import daemon


class FakeProc:
    pid = 4242


def test_start_detached_writes_pidfile(tmp_path):
    seen = {}

    def fake_popen(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["detached"] = kwargs.get("creationflags", 0)
        return FakeProc()

    with patch.object(daemon.subprocess, "Popen", side_effect=fake_popen):
        pid, log = daemon.start_detached(tmp_path)
    assert pid == 4242
    assert (tmp_path / "gateway.pid").read_text().strip() == "4242"
    assert str(log).endswith("gateway.log")
    assert "-m" in seen["cmd"] and "gateway" in seen["cmd"]


def test_start_refuses_double(tmp_path):
    (tmp_path / "gateway.pid").write_text("4242")
    with patch.object(daemon, "is_running", return_value=4242):
        try:
            daemon.start_detached(tmp_path)
        except RuntimeError as e:
            assert "already running" in str(e)
        else:
            raise AssertionError("expected RuntimeError")


def test_stop_kills_and_cleans(tmp_path):
    (tmp_path / "gateway.pid").write_text("1234")
    with patch.object(daemon, "is_running", return_value=1234), \
         patch.object(daemon.subprocess, "run", return_value=None), \
         patch.object(daemon.os, "kill", return_value=None):
        assert "1234" in daemon.stop(tmp_path)
    assert not (tmp_path / "gateway.pid").exists()


def test_stop_when_idle(tmp_path):
    assert "not running" in daemon.stop(tmp_path)


def test_is_running_none(tmp_path):
    assert daemon.is_running(tmp_path) is None
