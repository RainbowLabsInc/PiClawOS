import re

def _clean_query(query: str) -> str:
    q = query
    # Simulating the noise list from the code
    noise = ["nach", "einem", "nähe"]
    for word in noise:
        # The current implementation
        pattern = r"(?i)(?<![\w])" + re.escape(word) + r"(?![\w])"
        q = re.sub(pattern, " ", q)
    return " ".join(q.split()).strip()

test_str = "nach einem Raspberry Pi 5 nähe 21224"
print(f"Result: '{_clean_query(test_str)}'")

# What if we use a simpler boundary?
def _clean_query_v3(query: str) -> str:
    q = query
    noise = ["nach", "einem", "nähe"]
    for word in noise:
        # Using [^\w] with start/end anchors
        pattern = r"(?i)(?:^|[^\w])" + re.escape(word) + r"(?:[^\w]|$)"
        q = re.sub(pattern, " ", q)
    return " ".join(q.split()).strip()

print(f"Result V3: '{_clean_query_v3(test_str)}'")
