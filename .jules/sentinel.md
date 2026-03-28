## 2025-05-15 - [CRITICAL] Fix command injection in network tools
**Vulnerability:** A command injection vulnerability in `piclaw-os/piclaw/tools/network.py` allowed malicious input to be executed due to the use of string interpolation with `asyncio.create_subprocess_shell` in the `wifi_connect` function.
**Learning:** Using `create_subprocess_shell` with user input, even when wrapped in quotes, is unsafe because quotes can be escaped or bypassed.
**Prevention:** Always use `asyncio.create_subprocess_exec` and pass arguments securely as a `list[str]` instead of constructing a single shell command string.
