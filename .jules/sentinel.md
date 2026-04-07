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

## 2024-04-07 - Fix Path Traversal in File Saving
**Vulnerability:** The `write_workspace_file` function in `piclaw-os/piclaw/memory/store.py` used `pathlib`'s `/` operator with user input (`WORKSPACE_DIR / filename`) without resolving it. This allowed attackers to escape the intended directory boundary by providing paths containing `../` or absolute paths (e.g., `/etc/passwd`). In `pathlib`, if the right-hand operand is an absolute path, it entirely overrides the left-hand operand, creating a severe vulnerability where files could be written anywhere on the host filesystem.
**Learning:** `pathlib` operator `/` is insecure by default when used with untrusted user input since absolute paths override base paths, and relative lexical sequences (`../`) are not bounded. The correct protection mechanism requires `.resolve()` to normalize the path and `.is_relative_to()` to enforce directory jail boundaries.
**Prevention:** Always use `.resolve()` on BOTH the target path and the base path, then strictly enforce the boundary check via `.is_relative_to()`. Any user-provided path component must pass this check before passing to a system call like `write_text()` or `open()`.
