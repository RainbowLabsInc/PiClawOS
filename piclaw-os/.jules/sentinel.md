## 2024-04-28 - [Initial Entry]

## 2024-04-28 - [HIGH] Fix overly permissive CORS configuration
**Vulnerability:** The FastAPI application used `allow_origins=["*"]` in the CORS middleware, which allowed any origin to make cross-origin requests. Additionally, the configuration object `_cfg` was not loaded before the application initialization, meaning `cors_origins` from the configuration could not be applied at the time of FastAPI application creation.
**Learning:** In `piclaw-os/piclaw/api.py`, the configuration object `_cfg` must be initialized at the module level (e.g., `_cfg = load_cfg()`) before `app.add_middleware` is called to ensure dynamic settings like `cors_origins` are correctly applied during FastAPI app creation.
**Prevention:** Ensure that the configuration object is fully initialized and loaded before any dependent application initialization blocks (e.g. `app.add_middleware`) execute. Also, default `cors_origins` to restrict access to trusted origins (like `localhost` and local domains) instead of a wildcard.
