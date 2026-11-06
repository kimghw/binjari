"""Chrome 디버그 포트 제어권 잠금 (2026-11-06: 워처 둘이 같은 Chrome 에 붙어 한쪽이 죽은 사고 방지)."""

import os

import pytest

from ktx_watcher import chrome_launcher as cl


def make(tmp_path, monkeypatch):
    monkeypatch.setattr(cl, "_cdp_alive", lambda port, **kw: True)
    launcher = cl.ChromeLauncher(port=9555, user_data_dir=tmp_path, exe_path="chrome.exe")
    monkeypatch.setattr(launcher, "_move_to_vdesk", lambda: None)
    return launcher


def test_reuse_is_refused_while_another_live_watcher_controls_the_port(tmp_path, monkeypatch):
    (tmp_path / "ktx_watcher_cdp_9555.owner").write_text("4242", encoding="utf-8")
    monkeypatch.setattr(cl, "_pid_is_watcher", lambda pid: pid == 4242)
    with pytest.raises(RuntimeError, match="pid=4242"):
        make(tmp_path, monkeypatch).ensure_running()


def test_stale_lock_is_taken_over_and_released_on_shutdown(tmp_path, monkeypatch):
    lock = tmp_path / "ktx_watcher_cdp_9555.owner"
    lock.write_text("4242", encoding="utf-8")
    monkeypatch.setattr(cl, "_pid_is_watcher", lambda pid: False)   # 주인이 죽은 잠금
    launcher = make(tmp_path, monkeypatch)
    assert launcher.ensure_running() == "http://localhost:9555"
    assert lock.read_text(encoding="utf-8") == str(os.getpid())
    launcher.shutdown_if_owned()        # 재사용이라 Chrome 은 안 죽이지만 잠금은 푼다
    assert not lock.exists()


def test_own_pid_in_lock_is_not_a_conflict(tmp_path, monkeypatch):
    (tmp_path / "ktx_watcher_cdp_9555.owner").write_text(str(os.getpid()), encoding="utf-8")
    monkeypatch.setattr(cl, "_pid_is_watcher", lambda pid: True)
    assert make(tmp_path, monkeypatch).ensure_running() == "http://localhost:9555"


def test_pid_is_watcher_rejects_nonexistent_pid():
    assert cl._pid_is_watcher(0) is False
    assert cl._pid_is_watcher(2_000_000_000) is False
