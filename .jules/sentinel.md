## 2024-05-24 - Avoid Command Injection using create_subprocess_exec
**Vulnerability:** Command injection vulnerability in `create_subprocess_shell`. Multiple tools (e.g. `piclaw-os/piclaw/api.py`, `piclaw-os/piclaw/agents/watchdog.py`) use `asyncio.create_subprocess_shell` with user input, making them vulnerable to shell injection attacks.
**Learning:** Avoid `create_subprocess_shell` when the input is partially controlled by users.
**Prevention:** Use `create_subprocess_exec` passing the executable and arguments as a list.

## 2024-05-24 - Remove Remote Code Execution Endpoint
**Vulnerability:** Found a critical Remote Code Execution vulnerability in the codebase. The `api/shell` endpoint was intended for development and debugging but left intact in production code. It blindly passed untrusted input from request bodies into a `asyncio.create_subprocess_shell` execution.
**Learning:** Development endpoints left over in code can easily become production vulnerabilities, especially if they interact with the host system using insecure functions like `create_subprocess_shell`. This is a classic violation of "never trust user input", creating a massive risk for system takeover.
**Prevention:** Always remove development/debugging tools, routes, and credentials before deploying. Use automated static analysis tools or linters that flag unsafe functions like `create_subprocess_shell` to identify potential RCE points. If system commands are strictly necessary, avoid shells, pass commands securely (e.g. `create_subprocess_exec` using lists), and strongly sanitize input.

## 2024-05-24 - Fix Path Traversal in File Download
**Vulnerability:** A critical Path Traversal vulnerability was found in the `api/camera/image/{filename}` endpoint. The endpoint was vulnerable to accessing unauthorized files on the server using `..` in the `filename` parameter because `pathlib.Path.is_relative_to()` only performs a string-based check and does not resolve `..` components against the filesystem.
**Learning:** Checking `is_relative_to` on a user-controlled path without resolving it first is unsafe and leads to Path Traversal vulnerabilities.
**Prevention:** Always use `.resolve()` on the constructed path before checking if it is within an allowed directory boundaries. Like this: `path = (BASE_DIR / user_input).resolve()` and `path.is_relative_to(BASE_DIR.resolve())`.

## 2024-05-24 - Fix Command Injection in wifi_disconnect
**Vulnerability:** Command injection vulnerability in `piclaw-os/piclaw/tools/network.py` within the `wifi_disconnect` function. The tool used an f-string to construct a shell command: `f"nmcli dev disconnect {dev.strip()}"` and executed it via `_run()` which falls back to `asyncio.create_subprocess_shell` when passed a string.
**Learning:** Constructing commands via string concatenation and executing them using a shell executor exposes the system to command injection, even when part of the input seems harmless or originates from other tools. All arguments should be sanitized or passed individually.
**Prevention:** Pass commands as a list of arguments (e.g. `["nmcli", "dev", "disconnect", dev.strip()]`) rather than strings. This ensures they are safely executed via `asyncio.create_subprocess_exec` without shell expansion.

## 2024-04-06 - Path Traversal in Workspace File Writes
**Vulnerability:** A critical Path Traversal vulnerability was found in `piclaw/memory/store.py` inside the `write_workspace_file` function. The function concatenated `WORKSPACE_DIR` with a user-provided `filename` parameter without resolving or validating the resulting path. This could allow an attacker to write arbitrary files anywhere on the host filesystem by passing absolute paths or relative traversals (`../`).
**Learning:** `pathlib.Path`'s `/` operator has a dangerous default behavior: if the right operand is an absolute path (e.g., `WORKSPACE_DIR / "/etc/passwd"`), it completely overrides the left operand. This means relative traversal checks aren't enough; you must also protect against absolute path injection.
**Prevention:** To prevent path traversal vulnerabilities when constructing paths with user input (e.g., `BASE_DIR / filename`), always use `.resolve()` on both the constructed path and the base directory, then verify with `is_relative_to()` to protect against both absolute path injection and `..` lexical resolution flaws.
## 2024-05-24 - Validate Tool Arguments For Subprocess Exec
**Vulnerability:** Argument injection vulnerability in `piclaw/tools/network_security.py` where untrusted user input was passed as an argument to `asyncio.create_subprocess_exec` in commands like `whois <ip>` and `sudo iptables -A INPUT -s <ip> -j DROP`.
**Learning:** Even though `create_subprocess_exec` protects against *shell* injection, it does not protect against *argument* injection. If an unvalidated `ip` string starts with a dash (e.g. `-h` or `--help`), the underlying binary (`whois` or `iptables`) might interpret it as an unintended command-line flag instead of a positional argument.
**Prevention:** Strictly validate arguments passed to external tools to ensure they match the expected format (e.g. using `ipaddress.ip_address` for IP strings) before executing the subprocess.
## 2024-05-24 - Command Injection in Updater Tool
**Vulnerability:** The `updater.py` tool suffered from a command injection vulnerability where `cfg.repo_url` was passed directly to `asyncio.create_subprocess_shell` without sanitization.
**Learning:** Even internal parameters like `repo_url` in configuration tools can act as attack vectors if not properly escaped.
**Prevention:** Always use `shlex.quote` or `asyncio.create_subprocess_exec` instead of `create_subprocess_shell` for executing commands with external inputs.
