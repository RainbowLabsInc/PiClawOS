## 2024-05-24 - Avoid Command Injection using create_subprocess_exec
**Vulnerability:** Command injection vulnerability in `create_subprocess_shell`. Multiple tools (e.g. `piclaw-os/piclaw/api.py`, `piclaw-os/piclaw/agents/watchdog.py`) use `asyncio.create_subprocess_shell` with user input, making them vulnerable to shell injection attacks.
**Learning:** Avoid `create_subprocess_shell` when the input is partially controlled by users.
**Prevention:** Use `create_subprocess_exec` passing the executable and arguments as a list.
