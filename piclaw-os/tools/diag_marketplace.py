import sys
from pathlib import Path

# Adjust path to find piclaw-os
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from piclaw.tools.marketplace import _clean_query, marketplace_search, format_results
import asyncio

async def diag():
    print("=== MARKETPLACE DIAGNOSTICS ===")

    # 1. Test Cleaning
    test_query = "nach einem Raspberry Pi 5 Nähe 21224"
    cleaned = _clean_query(test_query)
    print(f"Original: {test_query}")
    print(f"Cleaned:  {cleaned}")

    if cleaned == "Raspberry Pi 5":
        print("✅ Cleaning successful")
    else:
        print("❌ Cleaning FAILED")

    # 2. Test Live Search (limited)
    print("\n--- Testing Live Search (Kleinanzeigen) ---")
    results = await marketplace_search(
        query="Raspberry Pi 5",
        platforms=["kleinanzeigen"],
        location="21224",
        radius_km=20,
        notify_all=True,
        max_results=3
    )

    print(f"Found: {results['total_found']} listings")
    if results['total_found'] > 0:
        print("✅ Live search working")
        print(format_results(results))
    else:
        print("❌ Live search returned NOTHING. Possible block or no hits.")

    # 3. Verify seen logic
    print("\n--- Verifying Seen Logic ---")
    results2 = await marketplace_search(
        query="Raspberry Pi 5",
        platforms=["kleinanzeigen"],
        location="21224",
        radius_km=20,
        notify_all=True,
        max_results=3
    )
    if results2['new_count'] == results['new_count']:
        print("✅ notify_all=True prevents filtering (correct)")
    else:
        print(f"❌ notify_all=True still filtered? {results['new_count']} vs {results2['new_count']}")

if __name__ == "__main__":
    asyncio.run(diag())
