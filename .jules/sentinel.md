## 2025-02-19 - [Fix Path Traversal in Camera Image Endpoint]
**Vulnerability:** Path traversal in `piclaw/api.py` allows arbitrary file read by exploiting `pathlib.Path.is_relative_to()`. Passing a filename like `../../etc/passwd` to `CAPTURE_DIR / filename` results in `/tmp/camera/../../etc/passwd`, which lexically evaluates as relative to `/tmp/camera`, even though it resolves outside the directory.
**Learning:** `pathlib.Path.is_relative_to()` performs purely lexical matching and does not resolve `..` sequences or symbolic links. Relying on it directly for security boundaries is dangerous and insufficient.
**Prevention:** Always call `.resolve()` on both the constructed path and the base directory prior to checking `.is_relative_to()` to ensure the canonical absolute path securely resides within the intended directory constraint.

## 2025-02-20 - [Fix Zip Slip / Path Traversal in Backup Restore]
**Vulnerability:** Path traversal (Zip Slip) in `piclaw/backup.py` allows arbitrary file overwrite during backup restoration. The code computed the destination path by stripping `"config/"` from the archive member name and appending it to `CONFIG_DIR`. A malicious archive containing a member like `config/../../../../etc/passwd` would resolve to `/etc/passwd` during write operations.
**Learning:** Archive file names (from tar or zip) are unstrustworthy user input. Naively joining them to a base directory without absolute path resolution and bounds checking creates severe Zip Slip vulnerabilities.
**Prevention:** Always use `.resolve()` to canonicalize the target destination path and verify it remains within the intended extraction directory using `.is_relative_to(BASE_DIR.resolve())` before extracting or writing files.
