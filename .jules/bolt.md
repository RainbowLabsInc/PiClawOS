## 2024-04-26 - Pre-compiled Regex over any() in Python
**Learning:** In hot paths (like intent detection in `_ha_shortcut` where every non-HA query fails), replacing generator expressions like `any(k in text for k in kw_tuple)` with a module-level pre-compiled regex `re.compile(r'(kw1|kw2)')` yields a 2-3x speedup, especially on "no match" paths.
**Action:** Always prefer module-level pre-compiled regex with an OR pattern over `any()` loops for matching one of multiple substrings in heavily trafficked paths.
