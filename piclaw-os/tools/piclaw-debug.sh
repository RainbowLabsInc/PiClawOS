#!/bin/bash
echo "====== PICLAW DEBUG REPORT ======"
echo "Zeit: $(date)"
echo ""
echo "=== SERVICES ==="
systemctl is-active piclaw-api piclaw-agent 2>/dev/null
echo ""
echo "=== LETZTER API LOG (20 Zeilen) ==="
sudo tail -20 /var/log/piclaw/api.log 2>/dev/null
echo ""
echo "=== MARKETPLACE TEST ==="
/opt/piclaw/.venv/bin/python3 - <<'EOF'
import asyncio, sys
sys.path.insert(0, '/home/piclaw/PiClawOS/piclaw-os')
from piclaw.agent import Agent
from piclaw.config import load
cfg = load()
a = Agent(cfg)
result = a._detect_marketplace_intent(
    "Suche Raspberry Pi 5 auf Kleinanzeigen.de im Umkreis von 30km um 21224"
)
print(f"Intent: {result}")
import inspect
src = inspect.getsource(Agent._run_internal)
print(f"notify_all: {'notify_all=True' in src}")
print(f"Calling marketplace: {'Calling marketplace' in src}")
async def test():
    from piclaw.tools.marketplace import marketplace_search, format_results
    r = await marketplace_search(query="Raspberry Pi 5", platforms=["kleinanzeigen"],
                                  location="21224", radius_km=30, notify_all=True, max_results=3)
    print(f"Direkttest: {r['total_found']} gefunden, {r['new_count']} neu")
asyncio.run(test())
EOF
echo ""
echo "=== SEEN FILE ==="
ls -la /etc/piclaw/marketplace_seen.json 2>/dev/null || echo "nicht vorhanden"
echo ""
echo "=== GIT VERSION ==="
cd ~/PiClawOS && git log --oneline -3
echo "====== ENDE ======"
