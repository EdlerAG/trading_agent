# QuantCore Execution Server

Asynchronous order execution, risk management, and telemetry platform for **Binance USD-M Perpetual Futures** built around a pluggable strategy interface (`IAlphaCartridge`).

See [`QuantCore-GrandMaster-Server/README.md`](QuantCore-GrandMaster-Server/README.md) for architecture diagrams, Smart Maker / Two-Phase rebalance mechanics, Post-Rebalance Reconciliation guarantees, environment configuration, and deployment details.

> **Repository Boundary:** Proprietary alpha modules, trained model weights (`*.joblib`), local operational scripts, research archives, runtime databases, and secrets are excluded via [`.gitignore`](.gitignore) and remain local-only.

---

## Repository Structure

```text
trading_agent/
├── .github/workflows/ci.yml        # Bytecode compilation & public server unit test CI
├── .gitignore                      # Public repo hygiene boundaries
├── requirements.lock               # Pinned Python environment dependencies
└── QuantCore-GrandMaster-Server/   # Async FastAPI + CCXT execution server, tests, and systemd/Caddy configs
```

---

## Quick Verification

```powershell
cd QuantCore-GrandMaster-Server
..\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```
