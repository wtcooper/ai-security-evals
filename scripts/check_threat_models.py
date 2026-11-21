#!/usr/bin/env python3
"""Check the formal threat models in threat-models/ and their copies in skills.

    python scripts/check_threat_models.py        # exit 1 on any problem

Checks:
  * every document listed in threat-models/index.json exists, and every document in the
    folder is listed;
  * each has the required sections, in order, and a metadata table naming what evaluates it;
  * every skill named in the index exists, and its references/threat-model.md is an exact
    copy of the canonical document (the sync script writes these);
  * review-threat-model carries a copy of every document;
  * for a modality benchmark with threats.json, every threat id it measures appears in its
    threat model, so the evaluation and the threat model cannot drift apart;
  * every skill that evaluates an asset class has a threat model (the ai-review stages other
    than review-threat-model are generic and exempt).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "threat-models"
SECTIONS = ("## 1. Executive summary", "## 2. Scope and assumptions", "## 3. System model",
            "## 4. Threats", "## 5. Evaluation coverage", "## 6. Design review checklist",
            "## 7. Residual risk and open questions", "## 8. References")
GENERIC = {"review-scope", "review-evidence", "review-criteria", "review-report"}
COLLECTOR = "review-threat-model"


def skill_dir(name: str) -> Path | None:
    found = sorted(ROOT.glob(f"plugins/*/skills/{name}"))
    return found[0] if found else None


def check_document(path: Path) -> list[str]:
    text = path.read_text()
    errs = []
    if not text.startswith("# Threat model: "):
        errs.append(f"{path.name}: must start with '# Threat model: <asset class>'")
    positions = [text.find("\n" + s + "\n") for s in SECTIONS]
    for section, pos in zip(SECTIONS, positions):
        if pos < 0:
            errs.append(f"{path.name}: missing section '{section}'")
    found = [p for p in positions if p >= 0]
    if found != sorted(found):
        errs.append(f"{path.name}: sections are out of order")
    head = text[:positions[0]] if positions[0] > 0 else text[:2000]
    if "| Evaluated by |" not in head:
        errs.append(f"{path.name}: the metadata table needs an 'Evaluated by' row")
    return errs


def check_repo(root: Path = ROOT) -> list[str]:
    errs: list[str] = []
    index = json.loads((FOLDER / "index.json").read_text())["models"]
    listed = {m["file"] for m in index}
    on_disk = {p.name for p in FOLDER.glob("*.md")} - {"README.md"}
    errs += [f"threat-models/{f}: listed in index.json but missing" for f in sorted(listed - on_disk)]
    errs += [f"threat-models/{f}: not listed in index.json" for f in sorted(on_disk - listed)]
    covered: set[str] = set()
    for m in index:
        doc = FOLDER / m["file"]
        if not doc.is_file():
            continue
        errs += check_document(doc)
        canonical = doc.read_text()
        for name in m["skills"]:
            covered.add(name)
            sd = skill_dir(name)
            if sd is None:
                errs.append(f"{m['file']}: names skill {name!r}, which does not exist")
                continue
            copy = sd / "references" / "threat-model.md"
            if not copy.is_file() or copy.read_text() != canonical:
                errs.append(f"{name}: references/threat-model.md is not a current copy of "
                            f"threat-models/{m['file']} (run tools/sync_skills.sh)")
            threats = sd / "threats.json"
            if threats.is_file():
                ids = [t["id"] for t in json.loads(threats.read_text())["threats"]]
                missing = [i for i in ids if not re.search(rf"(?<![\w-]){re.escape(i)}(?![\w-])", canonical)]
                if missing:
                    errs.append(f"{m['file']}: does not name {name}'s measured threats {missing}")
        collector = skill_dir(COLLECTOR)
        if collector is not None:
            copy = collector / "references" / "asset-threat-models" / m["file"]
            if not copy.is_file() or copy.read_text() != canonical:
                errs.append(f"{COLLECTOR}: references/asset-threat-models/{m['file']} is not a "
                            "current copy (run tools/sync_skills.sh)")
    for sd in sorted(root.glob("plugins/*/skills/*/")):
        if sd.name in GENERIC or sd.name == COLLECTOR:
            continue
        if sd.name not in covered:
            errs.append(f"{sd.name}: no threat model in threat-models/index.json covers this skill")
    return errs


def main() -> int:
    errs = check_repo()
    for e in errs:
        print("FAIL", e)
    if not errs:
        print("  ok — threat models are complete, listed, and copied into every skill that uses them")
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
