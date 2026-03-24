
## 2024-03-24 - Pre-compiled Regexes on Raspberry Pi
**Learning:** Compiling regex patterns repeatedly inside high-traffic loops, like `_detect_marketplace_intent`, severely impacts performance on resource-constrained environments like the Raspberry Pi. Dynamic loop iterations containing `re.escape()` and `re.sub()` over list elements significantly block execution.
**Action:** Always pre-compile regular expressions at the module level using `re.compile()`. Combine lists of stop-words and phrases into single regexes `(?:word1|word2)` sorted by length descending so the engine does not eagerly consume partial matches.
