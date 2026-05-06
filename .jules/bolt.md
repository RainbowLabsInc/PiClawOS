## 2024-04-26 - Pre-compiled Regex over any() in Python
**Learning:** In hot paths (like intent detection in `_ha_shortcut` where every non-HA query fails), replacing generator expressions like `any(k in text for k in kw_tuple)` with a module-level pre-compiled regex `re.compile(r'(kw1|kw2)')` yields a 2-3x speedup, especially on "no match" paths.
**Action:** Always prefer module-level pre-compiled regex with an OR pattern over `any()` loops for matching one of multiple substrings in heavily trafficked paths.

## 2024-04-30 - Chained native in checks over any() and pre-compiled regexes
**Learning:** In hot paths (like keyword intent detection in `_ha_shortcut`), replacing generator expressions like `any(k in text for k in kw_tuple)` with chained native `in` checks (e.g., `'kw1' in text or 'kw2' in text`) provides the maximum speedup. It outperforms both generator expressions and pre-compiled regexes significantly for simple substring presence checks against a single string.
**Action:** Always prefer chained native `in` checks over `any()` loops or pre-compiled regexes when checking a string for the presence of multiple, short, static substrings in heavily trafficked paths.

## 2024-05-02 - Module-level frozensets over local dynamic sets in hot paths
**Learning:** In highly trafficked hot paths, moving constant collections into local variables using the `{...}` syntax forces the Python interpreter to dynamically allocate and populate a new mutable set (`BUILD_SET`) on every single function invocation, causing significant performance overhead and unnecessary memory churn. Python automatically optimizes `x in (const1, const2)` into an O(1) lookup at compile time, meaning the "optimization" of moving it to a local set is actually a regression. Elevating these collections to module-level `frozenset` constants provides true O(1) zero-allocation lookups.
**Action:** Never define constant sets locally inside a hot-path function. Always elevate static collections to module-level or class-level `frozenset` constants to avoid the `BUILD_SET` allocation overhead.
## 2024-05-18 - [SQLite Greatest-N-Per-Group skip-scan]
**Learning:** SQLite's bare column aggregation (`SELECT MAX(ts)... GROUP BY name`) performs an inefficient full scan of all rows within a group, scaling poorly with large time-series tables like metrics databases.
**Action:** Use a recursive skip-scan Common Table Expression (CTE) to jump between distinct names using an index (`(name, ts)`), combining it with an `ORDER BY ts DESC LIMIT 1` subquery for O(1) lookups per group.
