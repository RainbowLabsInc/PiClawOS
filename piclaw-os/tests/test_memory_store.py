import pytest
from piclaw.memory.store import write_workspace_file

def test_write_workspace_file_success(tmp_path, monkeypatch):
    test_dir = tmp_path / "workspace"
    monkeypatch.setattr("piclaw.memory.store.WORKSPACE_DIR", test_dir)
    test_dir.mkdir(parents=True, exist_ok=True)

    res = write_workspace_file("test.txt", "hello")
    assert "Workspace file saved" in res
    assert (test_dir / "test.txt").exists()
    assert (test_dir / "test.txt").read_text() == "hello"

def test_write_workspace_file_path_traversal(tmp_path, monkeypatch):
    test_dir = tmp_path / "workspace"
    monkeypatch.setattr("piclaw.memory.store.WORKSPACE_DIR", test_dir)
    test_dir.mkdir(parents=True, exist_ok=True)

    with pytest.raises(ValueError, match="Workspace path must be within WORKSPACE_DIR"):
        write_workspace_file("../hacked.txt", "hacked")
