## 2024-04-21 - Secure nmcli password passing
**Vulnerability:** Command-line argument exposure via `nmcli`
**Learning:** `nmcli` exposes Wi-Fi passwords to the process list (visible via `ps aux`) when passed directly as `password <pass>` in the command string.
**Prevention:** Use the `nmcli` `--ask` flag combined with passing the password strictly through standard input (`stdin`) using `subprocess.run(input=...)` or `proc.communicate(input=...)`.
