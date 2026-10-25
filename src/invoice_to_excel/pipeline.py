"""Files in -> extracted, checked invoices out. Used by the web page and the scripts."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field

from .checks import Flag, check_batch
from .extract import Extraction, ExtractionError, Provider
from .schema import Invoice, invoice_from_dict

# Cost per million tokens (USD) used only for the on-screen estimate. Check Anthropic's
# pricing page and update when prices change; the estimate is labelled as approximate.
PRICES_PER_MTOK = {"claude-haiku-5-5": (0.10, 0.50)}


@dataclass
class Result:
    file_name: str
    invoice: Invoice | None
    flags: list[Flag] = field(default_factory=list)
    extraction: Extraction | None = None
    error: str | None = None

    @property
    def status(self) -> str:
        if self.error:
            return "Could not read"
        if any(f.severity == "error" for f in self.flags):
            return "Needs review"
        if self.flags:
            return "Check warnings"
        return "Looks right"


def process(files: list[tuple[str, bytes]], provider: Provider, today: dt.date | None = None,
            progress: Callable[[int, int, str], None] | None = None) -> list[Result]:
    """Read and check every file. `progress(done, total, file_name)` is called before each file."""
    results: list[Result] = []
    for i, (name, data) in enumerate(files):
        if progress:
            progress(i, len(files), name)
        try:
            ex = provider.extract(name, data)
            results.append(Result(name, invoice_from_dict(ex.data), extraction=ex))
        except ExtractionError as exc:
            results.append(Result(name, None, error=str(exc)))
    recheck(results, today)
    return results


def recheck(results: list[Result], today: dt.date | None = None) -> None:
    """Run all checks again, for example after a person edits a field."""
    readable = [r for r in results if r.invoice is not None]
    flags = check_batch([r.invoice for r in readable], [r.file_name for r in readable], today)
    for r, f in zip(readable, flags, strict=True):
        r.flags = f


def estimated_cost_usd(results: list[Result]) -> float | None:
    total, known = 0.0, False
    for r in results:
        ex = r.extraction
        if ex and ex.model in PRICES_PER_MTOK and (ex.input_tokens or ex.output_tokens):
            p_in, p_out = PRICES_PER_MTOK[ex.model]
            total += ex.input_tokens / 1e6 * p_in + ex.output_tokens / 1e6 * p_out
            known = True
    return total if known else None
