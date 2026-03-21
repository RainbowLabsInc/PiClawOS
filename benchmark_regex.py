import time
import re
import sys
import os

sys.path.insert(0, os.path.abspath('piclaw-os'))

# Import the module to benchmark
from piclaw.tools.marketplace import _parse_price, _clean_query

# We'll create a synthetic block of articles to benchmark the parsing loops
# specifically for _search_kleinanzeigen since it was mentioned in the issue.
dummy_html = """
<article data-adid="12345">
    <div class="text-module-begin">
        <a href="/s-anzeige/12345">Raspberry Pi 5 8GB</a>
    </div>
    <p class="aditem-main--middle--price">85 €</p>
    <span class="aditem-main--top--left">Hamburg</span>
</article>
""" * 1000 # 1000 articles

# Extract the articles first, simulating the pre-loop step
articles = re.findall(
    r'<article[^>]+data-adid="(\d+)"[^>]*>(.*?)</article>',
    dummy_html, re.DOTALL
)

def benchmark_kleinanzeigen_parsing():
    results = []
    start_time = time.perf_counter()

    # This simulates the exact loop in _search_kleinanzeigen
    for ad_id, content in articles:
        # Titel
        title_match = re.search(
            r'class="[^"]*text-module-begin[^"]*"[^>]*>\s*<a[^>]*>(.*?)</a>',
            content, re.DOTALL
        )
        if not title_match:
            title_match = re.search(r'<a[^>]*class="[^"]*ellipsis[^"]*"[^>]*>(.*?)</a>',
                                    content, re.DOTALL)
        title = " ".join(re.sub(r'<[^>]+>', ' ', title_match.group(1)).split()).strip() if title_match else ""

        # Preis
        price_match = re.search(r'<p[^>]*class="[^"]*aditem-main--middle--price[^"]*"[^>]*>(.*?)</p>',
                                 content, re.DOTALL)
        price_text = " ".join(re.sub(r'<[^>]+>', ' ', price_match.group(1)).split()).strip() if price_match else ""
        price = _parse_price(price_text)

        # Ort
        loc_match = re.search(r'<span[^>]*class="[^"]*aditem-main--top--left[^"]*"[^>]*>(.*?)</span>',
                               content, re.DOTALL)
        location_text = " ".join(re.sub(r'<[^>]+>', ' ', loc_match.group(1)).split()).strip() if loc_match else ""

        if not title:
            continue

        results.append({
            "id":       ad_id,
            "platform": "kleinanzeigen",
            "title":    title,
            "price":    price,
            "price_text": price_text,
            "location": location_text,
            "url":      f"https://www.kleinanzeigen.de/s-anzeige/{ad_id}",
        })

    end_time = time.perf_counter()
    return end_time - start_time, len(results)

# Run it multiple times to get a stable average
iterations = 100
total_time = 0

for _ in range(iterations):
    duration, count = benchmark_kleinanzeigen_parsing()
    total_time += duration

avg_time = (total_time / iterations) * 1000 # in ms
print(f"Kleinanzeigen Parsing (1000 items): {avg_time:.2f} ms")

# Benchmark _clean_query
def benchmark_clean_query():
    queries = [
        "[Web] Raspberry Pi 5 20km 20148 hamburg kaufen",
        "Suche ein günstiges angebot für raspberry pi 5 in münchen bitte",
        "was kostet ein raspberry pi 5 auf kleinanzeigen.de unter 100 euro",
        "Zeig mir ein schnäppchen für raspberry pi in meiner nähe",
        "finde raspberry pi 5 8gb ram"
    ] * 200 # 1000 queries

    start_time = time.perf_counter()
    for q in queries:
        _clean_query(q)
    end_time = time.perf_counter()
    return end_time - start_time

total_time_clean = 0
for _ in range(iterations):
    total_time_clean += benchmark_clean_query()

avg_time_clean = (total_time_clean / iterations) * 1000
print(f"Clean Query (1000 queries): {avg_time_clean:.2f} ms")
