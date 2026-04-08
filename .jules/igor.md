# 2026-04-05
## Vulnerability/Learning/Prevention
- **Learning**: `re.sub(r"\b...\b")` fails to correctly isolate location names that have whitespace or specific word boundaries where the words themselves start or end with non-word characters in certain unicode contexts, or are combined within sentences where the boundaries are tricky.
- **Prevention**: Use negative lookarounds `(?<![\w])` and `(?![\w])` which reliably match boundaries around variables that can contain any string (like "St. Pölten").
- **Learning**: The HA doctor logic used to block or fail fast because it didn't retry fetching the token.
- **Prevention**: Adding an async loop retry logic with sleep ensures robustness during startup.
