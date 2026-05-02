## 2025-02-19 - [Fix Path Traversal in Camera Image Endpoint]
**Vulnerability:** Path traversal in `piclaw/api.py` allows arbitrary file read by exploiting `pathlib.Path.is_relative_to()`. Passing a filename like `../../etc/passwd` to `CAPTURE_DIR / filename` results in `/tmp/camera/../../etc/passwd`, which lexically evaluates as relative to `/tmp/camera`, even though it resolves outside the directory.
**Learning:** `pathlib.Path.is_relative_to()` performs purely lexical matching and does not resolve `..` sequences or symbolic links. Relying on it directly for security boundaries is dangerous and insufficient.
**Prevention:** Always call `.resolve()` on both the constructed path and the base directory prior to checking `.is_relative_to()` to ensure the canonical absolute path securely resides within the intended directory constraint.

## 2025-02-20 - [Fix Zip Slip / Path Traversal in Backup Restore]
**Vulnerability:** Path traversal (Zip Slip) in `piclaw/backup.py` allows arbitrary file overwrite during backup restoration. The code computed the destination path by stripping `"config/"` from the archive member name and appending it to `CONFIG_DIR`. A malicious archive containing a member like `config/../../../../etc/passwd` would resolve to `/etc/passwd` during write operations.
**Learning:** Archive file names (from tar or zip) are unstrustworthy user input. Naively joining them to a base directory without absolute path resolution and bounds checking creates severe Zip Slip vulnerabilities.
**Prevention:** Always use `.resolve()` to canonicalize the target destination path and verify it remains within the intended extraction directory using `.is_relative_to(BASE_DIR.resolve())` before extracting or writing files.

## 2024-04-30 - [Fix command injection in EDITOR]
**Vulnerability:** User input from the `EDITOR` environment variable was directly concatenated into an `os.system()` call (`os.system(f"{editor} {path}")`), allowing for command injection if an attacker controls the `EDITOR` variable.
**Learning:** Even internal CLI tools or scripts that appear to just open an editor can be exploited if they use `os.system` without sanitizing environment variables. When using `shlex.split`, split ONLY the command/executable portion and append the explicit un-escaped file path to the resulting list (e.g., `shlex.split(editor) + [str(path)]`). This prevents unmatched quotes or spaces in the file path from breaking the tokenization process.
**Prevention:** Use `subprocess.call` with `shlex.split` to properly tokenize the command instead of raw string concatenation.
## 2025-05-01 - [Fix Command Injection in CLI Editor Invocation]
**Vulnerability:** The `cmd_soul` function in `piclaw-os/piclaw/cli.py` used `os.system(f"{editor} {path}")` to open the user's `$EDITOR`. If a malicious user controlled the `$EDITOR` environment variable (e.g., `EDITOR="nano; rm -rf /"`), it would execute arbitrary shell commands due to `os.system` interpreting the input via the shell.
**Learning:** Never pass unvalidated environment variables directly to `os.system()` or `subprocess` functions that use `shell=True`. Doing so creates trivial command injection vectors.
**Prevention:** Use `subprocess.call()` with a list of arguments. Parse the command string (like `$EDITOR`) securely using `shlex.split()` and append the safe, untainted arguments (like file paths) to the resulting list: `subprocess.call(shlex.split(editor) + [str(path)])`.

## 2026-05-02 - [Fix Command Injection in Service Command]
**Vulnerability:** A command injection vulnerability existed in `piclaw-os/piclaw/cli.py` inside the `cmd_service` function. The code used `os.system(f"sudo systemctl {action} piclaw-agent piclaw-api")` which formats user input directly into a shell string. This allows for arbitrary command execution if an attacker manages to control the `action` parameter (e.g. by passing `status; rm -rf /`).
**Learning:** System commands constructed via string concatenation with user input and executed through `os.system` are inherently insecure and lead to command injection. Even if currently only internal safe calls are made, defending against future unsafe calls is critical.
**Prevention:** Use `subprocess.run` or `subprocess.call` with a list of string arguments (e.g., `["sudo", "systemctl", action]`) instead of passing a formatted string to a shell execution function.

