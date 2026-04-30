## 2025-02-19 - [Fix Path Traversal in Camera Image Endpoint]
**Vulnerability:** Path traversal in `piclaw/api.py` allows arbitrary file read by exploiting `pathlib.Path.is_relative_to()`. Passing a filename like `../../etc/passwd` to `CAPTURE_DIR / filename` results in `/tmp/camera/../../etc/passwd`, which lexically evaluates as relative to `/tmp/camera`, even though it resolves outside the directory.
**Learning:** `pathlib.Path.is_relative_to()` performs purely lexical matching and does not resolve `..` sequences or symbolic links. Relying on it directly for security boundaries is dangerous and insufficient.
**Prevention:** Always call `.resolve()` on both the constructed path and the base directory prior to checking `.is_relative_to()` to ensure the canonical absolute path securely resides within the intended directory constraint.

## 2024-04-30 - [Fix command injection in EDITOR]
**Vulnerability:** User input from the `EDITOR` environment variable was directly concatenated into an `os.system()` call (`os.system(f"{editor} {path}")`), allowing for command injection if an attacker controls the `EDITOR` variable.
**Learning:** Even internal CLI tools or scripts that appear to just open an editor can be exploited if they use `os.system` without sanitizing environment variables. When using `shlex.split`, split ONLY the command/executable portion and append the explicit un-escaped file path to the resulting list (e.g., `shlex.split(editor) + [str(path)]`). This prevents unmatched quotes or spaces in the file path from breaking the tokenization process.
**Prevention:** Use `subprocess.call` with `shlex.split` to properly tokenize the command instead of raw string concatenation.
