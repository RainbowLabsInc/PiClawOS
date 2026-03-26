## 2024-05-18 - Prevent Command Injection in nmcli
**Vulnerability:** The `wifi_connect` tool in `network.py` directly interpolated user-provided `ssid` and `password` into a shell command string, allowing arbitrary command execution if a user included shell metacharacters like `"` and `;`.
**Learning:** Even simple CLI wrappers can introduce critical remote code execution risks if user input isn't strictly isolated from the shell interpreter.
**Prevention:** Never interpolate user input into strings executed via `asyncio.create_subprocess_shell`. Instead, pass arguments securely as a `list[str]` to `asyncio.create_subprocess_exec` to bypass the shell completely.
