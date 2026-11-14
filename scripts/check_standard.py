#!/usr/bin/env python3
"""Enforce the statically checkable rules of docs/skill-standard.md on every skill.

  python scripts/check_standard.py            # exit 1 on any violation
  python scripts/check_standard.py --legacy   # also list skills still exempt (pre-merge names)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
METHODS = ("benchmark", "redteam", "scan", "review")
MAX_LINES = 500
# Skills that predate the standard and are scheduled to be merged or rebuilt. An entry here
# is debt: remove it when the skill is brought up to the standard.
LEGACY: set[str] = {"control-codegen"}   # being replaced by coding-guidance-benchmark
# Phrases that set or advise an acceptance bar. A line may opt out with "standard: allow".
GATING = re.compile(
    r"\b(pass mark|passing score|acceptance threshold of|must (?:score|be) (?:at least|above|below)"
    r"|should (?:score|be) (?:at least|above|below) \d|fail the build|ci[- ]gat(?:e|ing)"
    r"|gate (?:ci|on)|unusable for ci|auto-?approv)", re.I)


def kind(name: str) -> str | None:
    if name.startswith("review-") or name.endswith("-review"):
        return "guided"
    if name.endswith(("-benchmark", "-redteam", "-scan")):
        return "measurement"
    return None


def check_skill(skill: Path) -> list[str]:
    name = skill.name
    md = skill / "SKILL.md"
    if not md.is_file():
        return [f"{name}: no SKILL.md"]
    text = md.read_text()
    lines = text.split("\n")
    errs = []
    k = kind(name)
    if k is None:
        errs.append(f"{name}: name must be <subject>-<method> with method in {METHODS}, "
                    "or review-<stage>")
    if len(lines) > MAX_LINES:
        errs.append(f"{name}: SKILL.md is {len(lines)} lines (limit {MAX_LINES}); move detail "
                    "to references/")
    for path in [md, *skill.glob("references/*.md")]:
        for i, line in enumerate(path.read_text().split("\n"), 1):
            if GATING.search(line) and "standard: allow" not in line:
                errs.append(f"{name}: {path.name}:{i} sets or advises an acceptance bar: "
                            f"{line.strip()[:80]!r}")
    if k == "measurement":
        for heading in ("PLAN", "RUN", "ANALYZE"):
            if not re.search(rf"^## .*\b{heading}\b", text, re.M):
                errs.append(f"{name}: SKILL.md needs a '## {heading}' section")
        for depth in ("smoke", "standard", "full"):
            if not re.search(rf"\b{depth}\b", text):
                errs.append(f"{name}: SKILL.md never mentions depth '{depth}'")
        if not re.search(r"^#+ .*smoke test", text, re.M | re.I):
            errs.append(f"{name}: SKILL.md needs a 'Smoke test' heading with a keyless command")
        if not any((skill / "tests").glob("test_*.py")) and not any(
                (skill / "tests").glob("*.test.cjs")):
            errs.append(f"{name}: no unit tests under tests/")
        if not (skill / "new_experiment.sh").is_file():
            errs.append(f"{name}: new_experiment.sh is not vendored")
    return errs


def check_repo(root: Path = ROOT, legacy: set[str] = LEGACY) -> list[str]:
    errs = []
    for skill in sorted(root.glob("plugins/*/skills/*/")):
        if skill.name in legacy:
            continue
        errs += check_skill(skill)
    return errs


def main(argv: list[str]) -> int:
    errs = check_repo()
    for e in errs:
        print("FAIL", e)
    present = sorted(s.name for s in ROOT.glob("plugins/*/skills/*/") if s.name in LEGACY)
    if "--legacy" in argv or present:
        print(f"  note — exempt until merged or rebuilt: {', '.join(present) or 'none'}")
    if not errs:
        print("  ok — every non-exempt skill meets the checked rules of docs/skill-standard.md")
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
