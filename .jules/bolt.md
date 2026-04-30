## 2024-04-26 - Pre-compiled Regex over any() in Python
**Learning:** In hot paths (like intent detection in `_ha_shortcut` where every non-HA query fails), replacing generator expressions like `any(k in text for k in kw_tuple)` with a module-level pre-compiled regex `re.compile(r'(kw1|kw2)')` yields a 2-3x speedup, especially on "no match" paths.
**Action:** Always prefer module-level pre-compiled regex with an OR pattern over `any()` loops for matching one of multiple substrings in heavily trafficked paths.

## 2024-04-30 - Chained native in checks over any() and pre-compiled regexes
**Learning:** In hot paths (like keyword intent detection in `_ha_shortcut`), replacing generator expressions like `any(k in text for k in kw_tuple)` with chained native `in` checks (e.g., `'kw1' in text or 'kw2' in text`) provides the maximum speedup. It outperforms both generator expressions and pre-compiled regexes significantly for simple substring presence checks against a single string.
**Action:** Always prefer chained native `in` checks over `any()` loops or pre-compiled regexes when checking a string for the presence of multiple, short, static substrings in heavily trafficked paths.
