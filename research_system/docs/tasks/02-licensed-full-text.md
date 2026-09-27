# Task 02: Complete licensed full-text retrieval

Priority: P1

Related work: TASK-008, TASK-010, TASK-011, TASK-030

Status: In progress

## Outcome

Regula retrieves full text only when machine-verifiable permission allows it, preserves provenance, and labels abstract-only evidence clearly when permitted full text is unavailable.

## Scope

- Define an allowlist of accepted licences and provider signals.
- Resolve open-access locations through provider metadata or an approved resolver such as Unpaywall.
- Download only canonical, permitted HTML or PDF content.
- Preserve licence, access URL, retrieval time, content hash, MIME type and extraction details.
- Handle retractions, redirects, expired links, paywalls, duplicate versions, size limits and partial downloads.
- Keep subscription content out of scope until legal and data-governance owners approve its use and retention.

## Implementation checklist

- [ ] Document accepted SPDX or provider licence values and ambiguous-value behavior.
- [ ] Add a resolver interface with explicit success, unavailable, forbidden and failed outcomes.
- [ ] Revalidate every redirect and resolved address before fetching content.
- [ ] Store immutable raw snapshots and passage locations for permitted content.
- [ ] Detect scanned PDFs and report OCR-required rather than silently ingesting empty text.
- [ ] Label evidence as full text, abstract only or metadata only in the API and dashboard.
- [ ] Add retraction and version-of-record checks where provider metadata supports them.
- [ ] Measure how often full text changes claim support compared with abstracts.

## Acceptance criteria

- Every downloaded document has a recorded licence basis and canonical source URL.
- Disallowed, ambiguous or paywalled content is not downloaded or used as evidence.
- Hash verification reproduces every retained snapshot.
- Extraction tests cover HTML, text PDF, scanned PDF, oversized response, partial download and duplicate versions.
- Missing permitted full text remains visible and cannot be converted into supporting placeholder text.
- A governance decision exists before any subscription-content adapter is enabled.

## Validation

```powershell
$env:PYTHONPATH = (Get-Location).Path
python -m pytest -q tests\test_hardening.py tests\test_source_discovery.py
```

Attach representative redacted provenance records, hash verification output and negative test results. Open-access resolution may be free, while publisher APIs or subscription content can require institutional accounts and licence fees.
