#!/usr/bin/env python3
"""Copy the harmful and benign prompts this skill renders as images, with their provenance.

    python3 corpus/build_prompts.py --source <app-benchmark corpus folder>

The source is the app-benchmark skill's licence-clean corpus (harmful.json and
benign_overrefusal.json). No prompt is written here; every one is copied with its source,
licence and original id. Rule, deterministic:

  * harmful: 8 XSTest unsafe prompts that have an XSTest safe contrast twin, and 8 AdvBench
    prompts;
  * benign: the 8 safe twins of those XSTest prompts, and 8 more XSTest safe prompts;
  * every prompt is one line of at most 120 characters (it has to fit on an image);
  * candidates are taken in the order of sha256("<salt>:<id>").

XSTest numbers its prompts in alternating blocks of 25 (safe, then their unsafe contrasts),
so the safe twin of `xstest-unsafe-<k>` is `xstest-safe-<k-25>`; a twin is used only when it
exists. Output: prompts.json beside this script, each prompt with
`source: {kind: benchmark, benchmark, id, license}`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SALT = "vision-model-benchmark-v1"
ADDED = "2026-11-21"   # when this selection was first copied; keep it when re-running
MAX_CHARS = 120
PER_GROUP = 8


def order(item_id: str) -> str:
    return hashlib.sha256(f"{SALT}:{item_id}".encode()).hexdigest()


def usable(prompt: str) -> bool:
    return "\n" not in prompt.strip() and len(prompt.strip()) <= MAX_CHARS


def load(path: Path) -> dict[str, dict]:
    rows = json.loads(path.read_text())
    return {r["metadata"]["id"]: {"prompt": r["vars"]["prompt"].strip(),
                                  "source": r["metadata"]["source"],
                                  "license": r["metadata"]["license"],
                                  "source_id": r["metadata"]["id"]} for r in rows}


def build(source: Path) -> dict:
    harmful = load(source / "harmful.json")
    benign = load(source / "benign_overrefusal.json")

    def twin(uid: str) -> str:
        return f"xstest-safe-{int(uid.rsplit('-', 1)[1]) - 25}"

    xs_unsafe = sorted((i for i, r in harmful.items() if r["source"] == "XSTest"
                        and usable(r["prompt"]) and twin(i) in benign
                        and usable(benign[twin(i)]["prompt"])), key=order)[:PER_GROUP]
    advbench = sorted((i for i, r in harmful.items() if r["source"] == "AdvBench"
                       and usable(r["prompt"])), key=order)[:PER_GROUP]
    twins = [twin(i) for i in xs_unsafe]
    more_safe = sorted((i for i, r in benign.items() if r["source"] == "XSTest"
                        and usable(r["prompt"]) and i not in twins), key=order)[:PER_GROUP]
    if min(len(xs_unsafe), len(advbench), len(more_safe)) < PER_GROUP:
        raise SystemExit("source corpus too small for the selection rule")

    def entry(pid: str, row: dict, kind: str, twin_of: str | None = None) -> dict:
        out = {"id": pid, "kind": kind, "prompt": row["prompt"],
               "source": {"kind": "benchmark", "benchmark": row["source"],
                          "id": row["source_id"], "license": row["license"]}}
        if twin_of:
            out["twin_of"] = twin_of
        return out

    prompts = []
    for i, uid in enumerate(xs_unsafe):
        prompts.append(entry(f"harm-xs-{i + 1:02d}", harmful[uid], "harmful"))
    for i, aid in enumerate(advbench):
        prompts.append(entry(f"harm-adv-{i + 1:02d}", harmful[aid], "harmful"))
    for i, sid in enumerate(twins):
        prompts.append(entry(f"benign-xs-{i + 1:02d}", benign[sid], "benign",
                             twin_of=f"harm-xs-{i + 1:02d}"))
    for i, sid in enumerate(more_safe):
        prompts.append(entry(f"benign-xs-{PER_GROUP + i + 1:02d}", benign[sid], "benign"))
    return {"_about": "Copied by build_prompts.py from the app-benchmark corpus; see NOTICE. "
                      "Each prompt keeps its source benchmark, licence and original id in "
                      "`source`.",
            "added": ADDED,
            "selection": {"salt": SALT, "max_chars": MAX_CHARS, "per_group": PER_GROUP},
            "prompts": prompts}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--source", required=True, help="folder holding harmful.json and "
                   "benign_overrefusal.json (the app-benchmark corpus)")
    p.add_argument("--out", default=str(Path(__file__).resolve().parent / "prompts.json"))
    a = p.parse_args(argv)
    data = build(Path(a.source))
    Path(a.out).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {len(data['prompts'])} prompts to {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
