"""Benchmark the extraction pipeline against ground truth: python -m invoiceiq.bench

Runs every sample PDF through the same pipeline the API uses (in upload order, so the
duplicate check sees earlier invoices) and writes bench/results.json.
"""

import argparse
import json
import platform
import statistics
from datetime import UTC, date, datetime
from pathlib import Path

from invoiceiq.extraction.llm import FakeProvider
from invoiceiq.extraction.pipeline import run_pipeline
from invoiceiq.extraction.types import FIELD_NAMES


def _same(name: str, got: str | None, expected: str) -> bool:
    if got is None:
        return False
    if name == "supplier_name":  # case/whitespace-insensitive
        return " ".join(got.split()).casefold() == " ".join(expected.split()).casefold()
    return got == expected


def run(samples: Path, today: date) -> dict:
    truth = json.loads((samples / "ground_truth.json").read_text())
    provider = FakeProvider()
    seen: set[tuple[str, str]] = set()
    per_field = {n: 0 for n in FIELD_NAMES}
    rules_complete, flag_correct, reason_correct, timings, details = 0, 0, 0, [], []
    llm_invoices, llm_requested, llm_filled = 0, 0, 0
    for item in truth:
        result = run_pipeline(
            (samples / item["file"]).read_bytes(),
            provider=provider,
            is_duplicate=lambda nit, num: (nit, num) in seen,
            today=today,
        )
        f = result.fields
        if f["supplier_nit"].value and f["invoice_number"].value:
            seen.add((f["supplier_nit"].value, f["invoice_number"].value))
        expected = item["fields"]
        wrong = [n for n in FIELD_NAMES if not _same(n, f[n].value, expected[n])]
        for n in FIELD_NAMES:
            per_field[n] += n not in wrong
        rules_ok = all(_same(n, result.rules_fields[n].value, expected[n]) for n in FIELD_NAMES)
        rules_complete += rules_ok
        flagged = result.needs_review
        flag_correct += flagged == item["expected_needs_review"]
        codes = sorted({i.code for i in result.issues if i.severity == "error"})
        reason_correct += codes == sorted(item["expected_reasons"])
        timings.append(result.elapsed_ms)
        llm_invoices += bool(result.llm_requested)
        llm_requested += len(result.llm_requested)
        llm_filled += len(result.llm_fields)
        details.append(
            {
                "file": item["file"],
                "template": item["template"],
                "wrong_fields": wrong,
                "llm_requested": result.llm_requested,
                "flagged": flagged,
                "expected_flagged": item["expected_needs_review"],
                "error_codes": codes,
                "expected_codes": item["expected_reasons"],
                "ms": round(result.elapsed_ms, 1),
            }
        )
    n = len(truth)
    flagged_expected = sum(1 for t in truth if t["expected_needs_review"])
    return {
        "dataset": "synthetic sample invoices (scripts/make_invoices.py)",
        "llm_fallback": "FakeProvider (offline; returns no values)",
        "invoices": n,
        "field_accuracy": {k: round(v / n, 4) for k, v in per_field.items()},
        "overall_field_accuracy": round(sum(per_field.values()) / (n * len(FIELD_NAMES)), 4),
        "fully_extracted_by_rules": rules_complete,
        "fully_extracted_by_rules_pct": round(100 * rules_complete / n, 1),
        "review_flag_correct": flag_correct,
        "expected_flagged": flagged_expected,
        "error_codes_exact_match": reason_correct,
        "avg_ms_per_invoice": round(statistics.mean(timings), 1),
        "max_ms_per_invoice": round(max(timings), 1),
        "invoices_sent_to_llm_fallback": llm_invoices,
        "fields_requested_from_llm": llm_requested,
        "fields_filled_by_llm": llm_filled,
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "details": details,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=Path, default=Path("data/samples"))
    parser.add_argument("--out", type=Path, default=Path("bench/results.json"))
    args = parser.parse_args()
    results = run(args.samples, date.today())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"Invoices: {results['invoices']}  (synthetic, FakeProvider fallback)")
    for name, acc in results["field_accuracy"].items():
        print(f"  {name:<15} {acc:6.1%}")
    print(
        f"Fully extracted by rules alone: {results['fully_extracted_by_rules']}/"
        f"{results['invoices']} ({results['fully_extracted_by_rules_pct']}%)"
    )
    print(
        f"Review flag correct: {results['review_flag_correct']}/{results['invoices']} "
        f"(expected flagged: {results['expected_flagged']}); exact error codes: "
        f"{results['error_codes_exact_match']}/{results['invoices']}"
    )
    print(
        f"LLM fallback: {results['invoices_sent_to_llm_fallback']} invoice(s), "
        f"{results['fields_requested_from_llm']} field(s) requested, "
        f"{results['fields_filled_by_llm']} filled"
    )
    print(
        f"Avg processing time: {results['avg_ms_per_invoice']} ms/invoice "
        f"(max {results['max_ms_per_invoice']} ms)"
    )
    print(f"Saved {args.out}")


if __name__ == "__main__":
    main()
