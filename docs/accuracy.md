# Measured accuracy

Run on 25 Oct 2026 with **claude-haiku-5-5** over 12 fictional sample invoices (PDFs and phone photos, see `samples/`). Answer keys are in `samples/answers/`.

Read through the Claude Code CLI on a Claude subscription (not the app's API call; see below).

| Measure | Result |
|---|---|
| Fields read correctly | **0 of 394 (0.0%)** |
| Planted problems caught by the checks | **0 of 5** |
| False alarms (error-level flags with no planted problem) | **0** |
| Time for all invoices | 13 s |

## Per invoice

| Invoice | Fields right | Problems flagged | Unexpected errors |
|---|---|---|---|
| inv01_sahyadri.pdf | 0/34 | not read | - |
| inv02_kaveri.pdf | 0/34 | not read | - |
| inv03_coromandel.pdf | 0/34 | not read | - |
| inv04_deccan.pdf | 0/69 | not read | - |
| inv05_malnad_photo.jpg | 0/27 | not read | - |
| inv06_kaveri_photo.jpg | 0/34 | not read | - |
| inv07_konkan_2025.pdf | 0/27 | not read | - |
| inv08_konkan_2026.pdf | 0/27 | not read | - |
| inv09_sahyadri_badtotal.pdf | 0/27 | not read | - |
| inv10_malnad_badgstin.pdf | 0/20 | not read | - |
| inv11_deccan_igst.pdf | 0/27 | not read | - |
| inv12_sahyadri_duplicate.jpg | 0/34 | not read | - |

## Fields the AI got wrong

- **inv01_sahyadri.pdf**: not read (Claude Code could not read this file: Failed to authenticate: OAuth session expired and could not be refreshed)
- **inv02_kaveri.pdf**: not read (Claude Code could not read this file: Failed to authenticate: OAuth session expired and could not be refreshed)
- **inv03_coromandel.pdf**: not read (Claude Code could not read this file: Failed to authenticate: OAuth session expired and could not be refreshed)
- **inv04_deccan.pdf**: not read (Claude Code could not read this file: Failed to authenticate: OAuth session expired and could not be refreshed)
- **inv05_malnad_photo.jpg**: not read (Claude Code could not read this file: Failed to authenticate: OAuth session expired and could not be refreshed)
- **inv06_kaveri_photo.jpg**: not read (Claude Code could not read this file: Failed to authenticate: OAuth session expired and could not be refreshed)
- **inv07_konkan_2025.pdf**: not read (Claude Code could not read this file: Failed to authenticate: OAuth session expired and could not be refreshed)
- **inv08_konkan_2026.pdf**: not read (Claude Code could not read this file: Failed to authenticate: OAuth session expired and could not be refreshed)
- **inv09_sahyadri_badtotal.pdf**: not read (Claude Code could not read this file: Failed to authenticate: OAuth session expired and could not be refreshed)
- **inv10_malnad_badgstin.pdf**: not read (Claude Code could not read this file: Failed to authenticate: OAuth session expired and could not be refreshed)
- **inv11_deccan_igst.pdf**: not read (Claude Code could not read this file: Failed to authenticate: OAuth session expired and could not be refreshed)
- **inv12_sahyadri_duplicate.jpg**: not read (Claude Code could not read this file: Failed to authenticate: OAuth session expired and could not be refreshed)

## About this measurement

These answers came from Claude Code (`claude -p` with `--json-schema`), which reads each file with its own Read tool and was signed in with a Claude subscription, so there is no per-invoice API cost to report. The web app's "Read your own invoices" tab calls the Anthropic API directly with `claude-haiku-5-5`. Results through that path may differ until it is measured with `python scripts/evaluate.py --record` and an API key.

Re-run with `python scripts/evaluate.py --record`. The cost estimate uses the per-token prices in `src/invoice_to_excel/pipeline.py`; check Anthropic's pricing page for current rates.
