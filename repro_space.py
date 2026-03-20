import re

def _clean_query(query: str) -> str:
    q = query
    # Simulating the noise list from the code
    noise = ["nach", "einem", "nähe"]
    for word in noise:
        # Let's try explicit space/boundary handling
        pattern = r"(?i)(?:\s|^)" + re.escape(word) + r"(?:\s|$)"
        q = re.sub(pattern, " ", q)
    return " ".join(q.split()).strip()

test_str = "nach einem Raspberry Pi 5 nähe 21224"
print(f"Result Space: '{_clean_query(test_str)}'")
