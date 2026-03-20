import re

def _clean_query(query: str) -> str:
    q = query
    noise = ["nach", "einem", "nähe"]
    for word in noise:
        # The previous pattern
        pattern = r"(?i)(?<![\w])" + re.escape(word) + r"(?![\w])"
        q = re.sub(pattern, " ", q)
    return " ".join(q.split()).strip()

test_str = "nach einem Raspberry Pi 5 nähe 21224"
print(f"Original: '{test_str}'")
print(f"Cleaned:  '{_clean_query(test_str)}'")

def _clean_query_v2(query: str) -> str:
    q = query
    noise = ["nach", "einem", "nähe"]
    for word in noise:
        # Let's try simpler word boundaries \b
        pattern = r"(?i)\b" + re.escape(word) + r"\b"
        q = re.sub(pattern, " ", q)
    return " ".join(q.split()).strip()

print(f"Cleaned V2: '{_clean_query_v2(test_str)}'")
