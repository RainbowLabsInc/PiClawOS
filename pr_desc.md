🚨 **Severity:** CRITICAL
💡 **Vulnerability:** SQL Injection in `_query_downsampled` in `piclaw-os/piclaw/metrics.py`. The `resolution` variable was being formatted directly into the SQL string via an f-string instead of using parameter binding.
🎯 **Impact:** Although the parameter is meant to be an integer, any bypassed input validation could lead to an attacker executing arbitrary SQL code, potentially leaking sensitive data or modifying database records.
🔧 **Fix:** Changed the query construction to use standard SQLite parameter binding (`?`) instead of string interpolation for the `resolution` variable, and added additional explicit type casting and bounds checking (`max(1, int(resolution))`).
✅ **Verification:** Verified by running the test suite on `test_metrics.py`, ensuring all tests pass and that the query still accurately fetches downsampled metrics.
