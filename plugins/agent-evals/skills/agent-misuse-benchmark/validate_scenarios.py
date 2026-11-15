#!/usr/bin/env python3
"""Check a scenario pack before running it.

    python validate_scenarios.py <pack dir> [--allow-placeholders]

Prints every problem and exits 1, or prints `ok` with a count. `--allow-placeholders` is for
the bundled example pack only.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scenarios  # noqa: E402


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        pack = scenarios.load_pack(args[0])
    except scenarios.PackError as exc:
        print(f"FAIL {exc}")
        return 1
    problems = scenarios.validate_pack(pack, "--allow-placeholders" in argv)
    for problem in problems:
        print("FAIL", problem)
    if not problems:
        pairs = pack["pairs"]
        cats = sorted({p["category"] for p in pairs})
        framings = sum(len(p.get("framings") or []) for p in pairs)
        print(f"ok — {len(pairs)} pairs ({len(pairs)} restricted + {len(pairs)} permitted), "
              f"{framings} extra framing(s), categories: {', '.join(cats)}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
