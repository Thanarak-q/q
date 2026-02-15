"""CI quality gate for benchmark results.

Checks that success rate, average cost, and average steps
meet minimum thresholds. Exits with code 1 if any check fails.

Usage:
    python benchmark/check.py benchmark/results/<timestamp>.json
"""

from __future__ import annotations

import json
import sys


def check(results_file: str) -> None:
    """Run quality gate checks on benchmark results.

    Args:
        results_file: Path to the benchmark results JSON file.
    """
    with open(results_file, encoding="utf-8") as f:
        results = json.load(f)

    total = results.get("total_challenges", 0)
    passed = results.get("passed", 0)

    if total == 0:
        print("No challenges found in results.")
        sys.exit(1)

    success_rate = passed / total * 100
    total_cost = results.get("total_cost_usd", 0)
    avg_cost = total_cost / total
    total_duration = results.get("total_duration_s", 0)

    # Compute average steps from individual results
    individual = results.get("results", [])
    avg_steps = (
        sum(r.get("steps", 0) for r in individual) / len(individual)
        if individual else 0
    )

    checks_passed = True

    # Quality gates
    if success_rate < 80:
        print(f"FAIL: Success rate {success_rate:.0f}% < 80%")
        checks_passed = False
    else:
        print(f"OK: Success rate {success_rate:.0f}%")

    if avg_cost > 0.15:
        print(f"FAIL: Avg cost ${avg_cost:.3f} > $0.15")
        checks_passed = False
    else:
        print(f"OK: Avg cost ${avg_cost:.3f}")

    if avg_steps > 8:
        print(f"FAIL: Avg steps {avg_steps:.1f} > 8")
        checks_passed = False
    else:
        print(f"OK: Avg steps {avg_steps:.1f}")

    print(f"\nSummary: {passed}/{total} passed | ${total_cost:.4f} total | {total_duration:.1f}s")

    if not checks_passed:
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <results.json>")
        sys.exit(1)
    check(sys.argv[1])
