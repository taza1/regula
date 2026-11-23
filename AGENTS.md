# AGENTS.md — Regula & Multi-Agent Research System Guide

Canonical project guide for **Antigravity** and all AI coding agents working in `regula`. Claude Code users also have [`CLAUDE.md`](./CLAUDE.md).

## Project Overview
This repository contains two distinct subsystems:
1. **Regula (repo root):** Terraform IaC security/compliance evaluation using OPA Rego (`bin/regula`, `lib/`, `conftest/`, `examples/`, `.github/workflows/main.yml`).
2. **Multi-Agent Research System (`research_system/`):** Active Python 3.11+ local/Azure research pipeline with SQLite persistence, FastAPI dashboard (`/dashboard`), bounded research planning, scope confirmation, scholarly discovery (OpenAlex, Crossref, arXiv), semantic fact-checking, critical review, claim ledger, blocker adjudication, and opt-in release governance (`.github/workflows/research-system.yml`).
   - Key docs: `research_system/README.md`, `research_system/ARCHITECTURE.md`, `research_system/docs/REVIEW_RELEASE_STATUS.md`, `research_system/docs/FUTURE_TASKS_AND_ARCHITECTURE_GATES.md`.

## Commands
### Research System (from `research_system/`, PowerShell)
```powershell
$env:PYTHONPATH = (Get-Location).Path
pytest -q                                           # Unit & integration tests (offline/mock)
.\run_local.ps1 -Port 8000                          # Local deterministic app (MODEL_PROVIDER=mock)
.\run_local.ps1 -Port 8000 -SourceConnector scholarly # Real scholarly metadata + mock model
```

Linux/bash equivalent:
```bash
cd research_system && PYTHONPATH=. pytest -q
```

## Critical Invariants
- **Never commit secrets or local databases:** Keep `.env`, Azure credentials, and `data/*.db` out of Git (only `.env.example`).
- **Entra auth, no stored Azure keys:** Azure mode (`run_azure.ps1`) uses `DefaultAzureCredential` — never hardcode or commit API keys.
- **Deterministic offline mock mode:** `MODEL_PROVIDER=mock` and `pytest -q` must work cleanly offline without calling Azure or incurring model costs.
- **Strict governance defaults:** Keep `ENABLE_REPORT_RELEASE` disabled by default (`501`) and preserve licensed full-text domain/licence verification, blocker adjudication, and hash-chained audit invariants.
- **Honest status boundaries:** Do not claim unimplemented Azure production adapters (Cosmos/Blob/Search/Service Bus) as live; keep claims aligned with `research_system/docs/REVIEW_RELEASE_STATUS.md`.

## Definition of Done
1. Run `pytest -q` from `research_system/` (with `PYTHONPATH` set) and ensure all tests pass.
2. For dashboard/UI changes, verify `/dashboard` in a browser (or Playwright regression test) and report results honestly.
3. Update `CHANGELOG.md` or relevant `research_system/docs/*.md` when behavior or governance gates change.
