## 2025-02-28 - [CRITICAL] Fix command injection in network tool
**Vulnerability:** The network tool (`piclaw-os/piclaw/tools/network.py`) used `asyncio.create_subprocess_shell` with string interpolation for user-provided network credentials (SSID and password).
**Learning:** `create_subprocess_shell` parses arguments through the system shell (e.g., `/bin/sh -c`), allowing shell metacharacters in variables like `password` to execute arbitrary commands if not properly sanitized.
**Prevention:** Replaced `create_subprocess_shell` with `create_subprocess_exec`, passing the command and all arguments as a list of strings (`*args`). This bypasses the shell interpreter entirely, ensuring parameters are passed strictly as data to the executable, preventing any form of command injection.
