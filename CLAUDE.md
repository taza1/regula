# CLAUDE.md

See [`AGENTS.md`](./AGENTS.md) and [`research_system/README.md`](./research_system/README.md) for full architecture and governance boundaries.

## Project
- **Regula + Multi-Agent Research System:**
  - Root: OPA Rego Terraform compliance rules (`bin/regula`, `lib/`, `conftest/`, `examples/`).
  - `research_system/`: Active Python 3.11+ FastAPI/SQLite multi-agent research system (offline mock mode + Azure AI Foundry via Entra `DefaultAzureCredential`, OpenAlex/Crossref/arXiv discovery, review & release governance gates).
- User works on Windows / PowerShell; CI runs Linux (`.github/workflows/research-system.yml`, `.github/workflows/main.yml`).

## Commands (from `research_system/`)
- Tests (PowerShell): `$env:PYTHONPATH = (Get-Location).Path; pytest -q`
- Local mock app: `.\run_local.ps1 -Port 8000` (opens `http://127.0.0.1:8000/dashboard`)

## Critical Invariants
- Never commit `.env`, API keys, or SQLite DBs (`data/`).
- Keep `MODEL_PROVIDER=mock` and `pytest -q` 100% offline/deterministic.
- Preserve Entra `DefaultAzureCredential`, `ENABLE_REPORT_RELEASE=false` default, licensed full-text checks, and hash-chained audit invariants.

## Definition of Done
1. Run `pytest -q` in `research_system/` and report results honestly.
2. For dashboard changes, verify `/dashboard` or run browser regression tests (note if skipped).
3. Update `CHANGELOG.md` / `research_system/docs/` when behavior changes.

## Style & Memory
- Keep responses short: what changed, verification result, anything needing a decision.
- Ask before live Azure runs, destructive actions, or outward-facing releases.
- Whenever corrected or told to remember something, add a concise rule to the right section of this file.
