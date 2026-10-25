# Case study: Invoice to Excel

*Portfolio project built on fictional invoices from made-up suppliers to a made-up store, "Namma Angadi Provisions" in Bengaluru.*

## The problem

A provisions store buys from a dozen suppliers. Every month someone types each purchase bill into a spreadsheet for the accountant: supplier, GSTIN, invoice number, date, each line, CGST/SGST/IGST and the total. Some bills arrive as PDFs, many as phone photos of printed bills.

Typing is slow, but the real cost is the mistakes: one wrong character in a supplier's GSTIN, a 12% rate the supplier forgot to update after September 2025, a bill entered twice because it came once by email and once as a photo, or a total that doesn't match its lines. These are found months later, if at all.

## What I built

A web page where the owner uploads a batch of bills and gets:

1. **Every bill read by AI** into the same fixed set of fields, including line items.
2. **Rule-based checks on every bill.** Plain arithmetic and GST rules, deliberately not AI, so they can be trusted to catch the AI's misreads as well as real mistakes on the bill.
3. **A review screen** that lists flagged bills first and shows the original bill beside the fields, with the reason for each flag. Fix, re-check, move on.
4. **An Excel workbook** (invoices, line items, every check, and a note on how it was made) or CSV files.

**Design rule: the AI reads, the rules check, a person decides.** The AI is told to copy what's printed, never to correct a total, and to leave a field empty rather than guess, because a confident guess is worse than a gap a person can see.

## The checks

| Planted problem in the samples | Check that catches it |
|---|---|
| Grand total ₹100 more than the lines and tax | Totals add up |
| One character wrong in the supplier's GSTIN | GSTIN check digit (mod-36 checksum) |
| IGST charged on a same-state sale | Supplier state vs place of supply |
| 12% GST on a bill dated after 22 Sep 2025 | Rate valid for the invoice date |
| The same bill uploaded as a PDF and a photo | Same supplier GSTIN + invoice number |

A 12% bill from August 2025 is included on purpose and must **not** be flagged. On the hand-typed answer keys, the checks flag exactly the 5 planted problems and nothing else.

## Decisions worth explaining

- **Structured output, not free text.** The request includes a JSON schema, so every answer has the same fields and types. If a model rejects the schema option, the tool falls back to instructions plus parsing, and says so on screen.
- **Checks don't use AI.** A second AI pass "checking" the first would share its blind spots. Arithmetic and a checksum don't.
- **A recorded demo.** The public page replays saved AI answers, so anyone can try it without a key and without costing anything, and every number shown came from a real run.
- **Small, cheap model by default.** Reading a printed invoice doesn't need the largest model. The model is a setting, and the evaluation script makes it easy to compare.
- **No accuracy claims without measurement.** `scripts/evaluate.py` scores every field against answer keys. Until it has been run, the README says accuracy is unmeasured.

## Results

Accuracy, time and cost per invoice: see [accuracy.md](accuracy.md) (pending the first evaluation run).

Engineering: 90 automated tests, including the request sent to the API, the fallback, plain-English messages for a bad key, rate limits and outages, the review page, and the Excel output.

## What I'd do next for a real client

Measure on 30–50 of their real bills (with permission) before promising a number, add a Tally import file, check new bills against previous months for duplicates, and compare against GSTR-2B to find bills the supplier hasn't filed.
