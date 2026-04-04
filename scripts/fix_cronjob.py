#!/usr/bin/env python3
"""
CronJob_0715 auf direct_tool='system_report' umstellen.
Ausführen: sudo /opt/piclaw/venv/bin/python3 /opt/piclaw/scripts/fix_cronjob.py

Spart täglich ~3-5 LLM-Calls (Groq/NIM Token-Budget).
"""
import json, subprocess
from pathlib import Path

SUBAGENTS = Path("/etc/piclaw/subagents.json")

data = json.loads(SUBAGENTS.read_text())
patched = 0
for k, v in data.items():
    if v.get("name", "").startswith("CronJob_"):
        # Nur Systembericht-Jobs umstellen (nicht Service-Status-Jobs)
        task = (v.get("description", "") + v.get("mission", "")).lower()
        is_service_job = any(w in task for w in ("service", "dienst", "prozess"))
        if not is_service_job:
            v["direct_tool"] = "system_report"
            v["mission"] = "Direct tool mode: system_report"
            print(f"  ✅ {v['name']} → direct_tool=system_report")
            patched += 1
        else:
            print(f"  ⏭  {v['name']} (Service-Job) → unverändert (nutzt LLM)")

if patched:
    SUBAGENTS.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\n{patched} CronJob(s) gepatcht. Neustart empfohlen:")
    ans = input("Jetzt neustarten? [j/N] ").strip().lower()
    if ans in ("j", "y"):
        subprocess.run(["sudo", "systemctl", "restart", "piclaw-agent"])
        print("✅ piclaw-agent neu gestartet")
else:
    print("Keine passenden CronJobs gefunden.")
