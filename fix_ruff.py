with open('piclaw-os/piclaw/agent.py', 'r') as f:
    content = f.read()

content = content.replace('mission = f"Direct tool mode: system_report"', 'mission = "Direct tool mode: system_report"')

with open('piclaw-os/piclaw/agent.py', 'w') as f:
    f.write(content)
