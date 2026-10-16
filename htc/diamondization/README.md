# 🐦‍🔥 Phoenix Ω∞ HTC Diamondization Pack

## Delivered
- manifest_core.py: FastAPI API, SQLite WAL ledger, proposal-only Gemini integration, hash-chained audit events, integrity verification, and record retrieval.
- tests/test_core.py: regression tests for WAL, chain linkage, tamper detection, missing credentials, 404 behavior, mocked proposal persistence, concurrent writes, and input bounds.
- .github/workflows/htc-c641.yml: CI workflow for compilation and tests.

## Termux setup
    pkg update && pkg install python
    python -m venv .venv && source .venv/bin/activate
    python -m pip install -r requirements.txt
    python -m py_compile manifest_core.py tests/test_core.py
    python -m pytest -q
    export GEMINI_API_KEY='YOUR_KEY'
    export GEMINI_MODEL='MODEL_ENABLED_FOR_YOUR_ACCOUNT'
    python -m uvicorn manifest_core:app --host 127.0.0.1 --port 8000

Use a model identifier documented and enabled for your actual account. The supplied default gemini-4-argon is retained from the original manifest, not represented as live-verified.

## Evidence boundaries
Hash chaining is tamper-evident, not immutable against a privileged database rewrite. AI output is stored as a proposal; generated code is not executed. Live Gemini access, target-device installation, and external Arweave/AO/OTS/Bitcoin anchoring remain separate gates requiring real receipts.
