## 2024-05-24 - Avoid Command Injection using create_subprocess_exec
**Vulnerability:** Command injection vulnerability in `create_subprocess_shell`. Multiple tools (e.g. `piclaw-os/piclaw/api.py`, `piclaw-os/piclaw/agents/watchdog.py`) use `asyncio.create_subprocess_shell` with user input, making them vulnerable to shell injection attacks.
**Learning:** Avoid `create_subprocess_shell` when the input is partially controlled by users.
**Prevention:** Use `create_subprocess_exec` passing the executable and arguments as a list.

## 2024-05-24 - Remove Remote Code Execution Endpoint
**Vulnerability:** Found a critical Remote Code Execution vulnerability in the codebase. The `api/shell` endpoint was intended for development and debugging but left intact in production code. It blindly passed untrusted input from request bodies into a `asyncio.create_subprocess_shell` execution.
**Learning:** Development endpoints left over in code can easily become production vulnerabilities, especially if they interact with the host system using insecure functions like `create_subprocess_shell`. This is a classic violation of "never trust user input", creating a massive risk for system takeover.
**Prevention:** Always remove development/debugging tools, routes, and credentials before deploying. Use automated static analysis tools or linters that flag unsafe functions like `create_subprocess_shell` to identify potential RCE points. If system commands are strictly necessary, avoid shells, pass commands securely (e.g. `create_subprocess_exec` using lists), and strongly sanitize input.
