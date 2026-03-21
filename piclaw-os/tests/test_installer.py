from pathlib import Path

from piclaw.tools.installer import get_ipc_paths

def test_get_ipc_paths(monkeypatch, tmp_path):
    # Mock CONFIG_DIR
    monkeypatch.setattr("piclaw.tools.installer.CONFIG_DIR", tmp_path)

    # Call the function
    ipc_dir, req_file, res_file = get_ipc_paths()

    # Verify the return types
    assert isinstance(ipc_dir, Path)
    assert isinstance(req_file, Path)
    assert isinstance(res_file, Path)

    # Verify the paths are correct relative to the mocked CONFIG_DIR
    assert ipc_dir == tmp_path / "ipc"
    assert req_file == tmp_path / "ipc" / "install_req.json"
    assert res_file == tmp_path / "ipc" / "install_res.json"

    # Verify the function does NOT create the directory or files
    assert not ipc_dir.exists()
    assert not req_file.exists()
    assert not res_file.exists()
