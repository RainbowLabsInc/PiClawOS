import re

with open('piclaw-os/piclaw/agent.py', 'r') as f:
    content = f.read()

# We need to add `# noqa: E402` to imports occurring after the constants block.

def add_noqa(match):
    line = match.group(0)
    if '# noqa' not in line:
        return line + '  # noqa: E402'
    return line

# Find imports that follow our custom constants block
content = re.sub(r'^(from piclaw.*?import.*?)$', add_noqa, content, flags=re.MULTILINE)

with open('piclaw-os/piclaw/agent.py', 'w') as f:
    f.write(content)
