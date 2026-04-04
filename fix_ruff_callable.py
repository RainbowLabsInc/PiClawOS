with open('piclaw-os/piclaw/agent.py', 'r') as f:
    content = f.read()

content = content.replace('from collections.abc import Callable', 'from collections.abc import Callable  # noqa: E402')

with open('piclaw-os/piclaw/agent.py', 'w') as f:
    f.write(content)
