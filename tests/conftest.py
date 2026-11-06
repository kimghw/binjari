import pytest


@pytest.fixture(autouse=True)
def _isolate_reserved_state(tmp_path, monkeypatch):
    """확보 기록 영구저장 파일이 테스트 중 실제 runs/reserved_state.json 을 건드리지 않게 임시 경로로."""
    from ktx_watcher import main as watcher_main
    monkeypatch.setattr(watcher_main, "_RESERVED_STATE_PATH", tmp_path / "reserved_state.json")
    yield
