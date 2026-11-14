#!/usr/bin/env python3
"""Print count / mean / min / max for each numeric column of a CSV file."""
import csv
import sys


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: column_stats.py <file.csv>", file=sys.stderr)
        return 2
    cols: dict[str, list[float]] = {}
    skipped: set[str] = set()
    with open(sys.argv[1], newline="") as fh:
        for row in csv.DictReader(fh):
            for name, value in row.items():
                try:
                    cols.setdefault(name, []).append(float(value))
                except (TypeError, ValueError):
                    skipped.add(name)
    print(f"{'column':<20} {'n':>6} {'mean':>12} {'min':>12} {'max':>12}")
    for name, vals in cols.items():
        if name in skipped or not vals:
            continue
        print(f"{name:<20} {len(vals):>6} {sum(vals) / len(vals):>12.4f} {min(vals):>12.4f} {max(vals):>12.4f}")
    if skipped:
        print("skipped non-numeric columns: " + ", ".join(sorted(skipped)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
