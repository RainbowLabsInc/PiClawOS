## 2024-04-26 - Pre-compiled Regex over any() in Python
**Learning:** In hot paths (like intent detection in `_ha_shortcut` where every non-HA query fails), replacing generator expressions like `any(k in text for k in kw_tuple)` with a module-level pre-compiled regex `re.compile(r'(kw1|kw2)')` yields a 2-3x speedup, especially on "no match" paths.
**Action:** Always prefer module-level pre-compiled regex with an OR pattern over `any()` loops for matching one of multiple substrings in heavily trafficked paths.

## 2024-05-18 - Set Conversion for O(1) Lookups in List Comprehensions
**Learning:** When filtering items using a list comprehension in a hot path (e.g., `[w for w in words if w not in exclusion_list]`), performing the exclusion check against a list or concatenated tuple results in an O(N) lookup for every word. Converting the exclusion collection to a `set()` before the loop reduces the lookup time complexity to O(1), leading to measurable execution speed improvements, particularly when the string list scales up.
**Action:** Always pre-calculate sets for exclusion or inclusion lists used inside hot-path list comprehensions to ensure O(1) membership checks.
