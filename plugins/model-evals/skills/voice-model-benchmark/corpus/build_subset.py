#!/usr/bin/env python3
"""Maintainer script: rebuild this skill's vendored corpus from the app-benchmark corpus.

    python corpus/build_subset.py --source <dir holding harmful.json and benign_overrefusal.json>
    python corpus/build_subset.py --source <dir> --check     # exit 1 if the copy has drifted

Nothing is authored here. A case is copied when it can be SPOKEN as one short utterance:
it comes from a source of plain single-sentence requests, has no line breaks and is at most
MAX_CHARS characters. That leaves out the long code-bearing cyber prompts and the flattened
multi-turn prompts, whose layout (bullets, numbered lists, Python literals) has no spoken form.

Output (deterministic, so a drift check is a byte comparison):
    cases.jsonl     one case per line: id, type (harmful | benign), category, source, license, prompt
    manifest.json   the rule, counts, and hashes of the inputs and the output
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAX_CHARS = 200
# file -> (case type in this skill, sources taken from it)
INPUTS = {
    "harmful.json": ("harmful", ("AdvBench", "XSTest")),
    "benign_overrefusal.json": ("benign", ("XSTest", "PromptInject")),
}


def speakable(prompt: str) -> bool:
    return 0 < len(prompt) <= MAX_CHARS and "\n" not in prompt


def build(source: Path) -> tuple[str, dict]:
    lines, inputs, seen = [], {}, set()
    for name, (case_type, sources) in INPUTS.items():
        raw = (source / name).read_bytes()
        inputs[name] = hashlib.sha256(raw).hexdigest()
        for row in json.loads(raw):
            meta, prompt = row["metadata"], row["vars"]["prompt"]
            if meta["source"] not in sources or not speakable(prompt):
                continue
            if meta["id"] in seen:
                raise ValueError(f"duplicate case id {meta['id']}")
            seen.add(meta["id"])
            lines.append(json.dumps({
                "id": meta["id"], "type": case_type, "category": meta.get("category"),
                "source": meta["source"], "license": meta["license"], "prompt": prompt,
            }, sort_keys=True, ensure_ascii=False))
    text = "\n".join(lines) + "\n"
    rows = [json.loads(line) for line in lines]
    manifest = {
        "built_from": "app-benchmark corpus (harmful.json, benign_overrefusal.json)",
        "rule": {"max_chars": MAX_CHARS, "no_line_breaks": True,
                 "sources": {k: list(v[1]) for k, v in INPUTS.items()}},
        "input_sha256": inputs,
        "cases_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "counts": {
            "total": len(rows),
            "by_type": dict(sorted(Counter(r["type"] for r in rows).items())),
            "by_type_source_license": {
                f"{t}/{s}/{lic}": n for (t, s, lic), n in sorted(
                    Counter((r["type"], r["source"], r["license"]) for r in rows).items())},
        },
    }
    return text, manifest


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--source", required=True, help="directory of the app-benchmark corpus")
    p.add_argument("--check", action="store_true", help="compare instead of writing")
    args = p.parse_args(argv)
    text, manifest = build(Path(args.source))
    manifest_text = json.dumps(manifest, indent=2) + "\n"
    if args.check:
        same = ((HERE / "cases.jsonl").read_text() == text
                and (HERE / "manifest.json").read_text() == manifest_text)
        print("corpus subset is current" if same else "DRIFT: corpus subset differs from source")
        return 0 if same else 1
    (HERE / "cases.jsonl").write_text(text)
    (HERE / "manifest.json").write_text(manifest_text)
    print(json.dumps(manifest["counts"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
