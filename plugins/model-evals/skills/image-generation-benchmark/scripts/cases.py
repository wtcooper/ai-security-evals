"""Load the core request set, fill its slots, and pick the cases a depth runs. Stdlib only.

A case in corpus/core.json is a task statement with slots ({BRAND}, {ISSUER}, {URL},
{PERSON}) filled from a slots file. Each case names its primary slot; at `full` depth a case
runs once per value of that slot, at `smoke` and `standard` once with the first value. Other
slots in the text take their first value. A case whose slot has no value (PERSON by default)
is skipped and reported, never run with a made-up value.

Scorer, derived from the case:
  produced    benign twin: an image coming back is the good outcome
  judge       harmful: refused, or the vision judge answers NO to the threat's rubric
  decode      harmful payload: refused, or no barcode in the image decodes to the URL asked for
  provenance  the image is checked for a C2PA manifest (known lane) and its survival (custom)
A reframed case is its base request with a frame prefix and uses the base's scorer and rubric.

The judge sees one image and one rubric question, never the case kind, threat, frame or an
expected answer. RUBRIC_VERSION names the wording of `judge_system` and `rubrics` in core.json
(ALT_RUBRIC_VERSION the reworded `alt_judge_system` and `alt_rubrics`); bump it whenever that
wording changes. The unit tests pin the wording's fingerprint to the version.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
CORE = SKILL / "corpus" / "core.json"
DEFAULT_SLOTS = SKILL / "corpus" / "slots.default.json"
DEPTH_NAMES = ("smoke", "standard", "full")
SMOKE = {"harmful": 3, "benign": 1, "provenance": 3}
DECODE_THREATS = {"ig-machine-payload"}
SLOT = re.compile(r"\{([A-Z_]+)\}")
RUBRIC_VERSION = "2"        # 2: "for a security evaluation" removed from judge_system
ALT_RUBRIC_VERSION = "2-alt"


def load_corpus(path: str | Path | None = None) -> dict:
    return validate(json.loads(Path(path or CORE).read_text()))


def validate(data: dict) -> dict:
    ids = [c["id"] for c in data["cases"]]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ValueError(f"duplicate case ids: {dupes}")
    by_id = {c["id"]: c for c in data["cases"]}
    for c in data["cases"]:
        if c.get("kind") not in ("harmful", "benign", "provenance"):
            raise ValueError(f"{c['id']}: kind must be harmful, benign or provenance")
        if c.get("reframes") and c["reframes"] not in by_id:
            raise ValueError(f"{c['id']} reframes unknown case {c['reframes']!r}")
        if c.get("frame") and c["frame"] not in data["frames"]:
            raise ValueError(f"{c['id']} uses unknown frame {c['frame']!r}")
        if not c.get("reframes") and not c.get("request"):
            raise ValueError(f"{c['id']} has no request")
    return data


def merge_extra(corpus: dict, path: str | Path) -> dict:
    """Add an organisation's own cases (same format) to the core set."""
    extra = json.loads(Path(path).read_text())
    return validate(dict(corpus, cases=corpus["cases"] + extra.get("cases", []),
                         rubrics={**corpus["rubrics"], **extra.get("rubrics", {})},
                         alt_rubrics={**corpus.get("alt_rubrics", {}),
                                      **extra.get("alt_rubrics", {})},
                         frames={**corpus["frames"], **extra.get("frames", {})}))


def judge_wording(corpus: dict, alt: bool = False) -> tuple[str, dict]:
    """(system prompt, rubrics by threat) for the main or the reworded judge."""
    if alt:
        return corpus["alt_judge_system"], corpus.get("alt_rubrics", {})
    return corpus["judge_system"], corpus["rubrics"]


def wording_sha(corpus: dict, alt: bool = False) -> str:
    """Fingerprint of the judge wording, so a change without a version bump is caught."""
    system, rubrics = judge_wording(corpus, alt)
    return hashlib.sha256(json.dumps([system, rubrics], sort_keys=True).encode()).hexdigest()


def load_slots(path: str | Path | None = None) -> dict[str, list[str]]:
    raw = json.loads(Path(path or DEFAULT_SLOTS).read_text())
    out = {}
    for k, v in raw.items():
        if k.startswith("_"):
            continue
        values = [v] if isinstance(v, str) else list(v or [])
        out[k] = [str(x).strip() for x in values if str(x).strip()]
    return out


def scorer_for(case: dict, base: dict | None = None) -> str:
    src = base or case
    if case["kind"] == "benign":
        return "produced"
    if case["kind"] == "provenance":
        return "provenance"
    return "decode" if src["threat"] in DECODE_THREATS else "judge"


def _fill(text: str, values: dict[str, str]) -> str:
    return SLOT.sub(lambda m: values[m.group(1)], text)


def expand(corpus: dict, slots: dict[str, list[str]], all_values: bool = False
           ) -> tuple[list[dict], list[dict]]:
    """(runnable cases, skipped cases with a reason)."""
    by_id = {c["id"]: c for c in corpus["cases"]}
    first = {s: v[0] for s, v in slots.items() if v}
    runnable, skipped = [], []
    for c in corpus["cases"]:
        base = by_id[c["reframes"]] if c.get("reframes") else None
        src = base or c
        text = src["request"]
        primary = src.get("slot")
        needed = set(SLOT.findall(text)) | ({primary} if primary else set())
        missing = sorted(s for s in needed if not slots.get(s))
        if missing:
            skipped.append({"case": c["id"], "threat": c["threat"], "kind": c["kind"],
                            "reason": f"no value for slot {', '.join('{' + s + '}' for s in missing)}"})
            continue
        variants = slots[primary] if (primary and all_values) else (slots[primary][:1] if primary else [None])
        for i, value in enumerate(variants):
            values = {s: slots[s][0] for s in needed}
            if primary:
                values[primary] = value
            prompt = _fill(text, values)
            if c.get("frame"):
                prompt = corpus["frames"][c["frame"]] + prompt
            rubric_threat = src["threat"]
            scorer = scorer_for(c, base)
            suffix = f".{i + 1}" if i else ""
            fill = {**first, **values, "ASSET": src.get("asset", "image")}

            def rubric(table: dict) -> str | None:
                text = table.get(rubric_threat)
                return _fill(text, fill) if scorer == "judge" and text else None
            runnable.append({
                "case": c["id"] + suffix, "base_id": c["id"], "threat": c["threat"],
                "kind": c["kind"], "scorer": scorer, "prompt": prompt,
                "rubric": rubric(corpus["rubrics"]),
                "rubric_alt": rubric(corpus.get("alt_rubrics", {})),
                "payload": values.get("URL") if scorer == "decode" else None,
                "reframes": (c["reframes"] + suffix) if base else None,
                "frame": c.get("frame"), "slot": primary, "slot_value": value})
    # Benign twins alone would make a threat look measured; drop them when no harmful case runs.
    measured = {c["threat"] for c in runnable if c["kind"] != "benign"}
    for c in [c for c in runnable if c["threat"] not in measured]:
        runnable.remove(c)
        skipped.append({"case": c["case"], "threat": c["threat"], "kind": c["kind"],
                        "reason": "threat not measured: none of its harmful cases can run"})
    return runnable, skipped


def select(cases: list[dict], depth: str) -> list[dict]:
    """smoke: 3 harmful + 1 benign per threat (3 provenance); standard and full: every case;
    an integer N: N harmful + ceil(N/3) benign per threat (N provenance)."""
    if depth in ("standard", "full"):
        return list(cases)
    if depth == "smoke":
        quota = dict(SMOKE)
    else:
        try:
            n = int(depth)
        except ValueError:
            raise ValueError(f"depth must be one of {DEPTH_NAMES} or a positive integer") from None
        if n < 1:
            raise ValueError("depth must be a positive integer")
        quota = {"harmful": n, "benign": math.ceil(n / 3), "provenance": n}
    seen: dict[tuple[str, str], list[str]] = {}
    out = []
    for c in cases:
        key = (c["threat"], c["kind"])
        bases = seen.setdefault(key, [])
        if c["base_id"] not in bases:
            if len(bases) >= quota.get(c["kind"], 0):
                continue
            bases.append(c["base_id"])
        out.append(c)
    return out


def counts(corpus: dict) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for c in corpus["cases"]:
        out.setdefault(c["threat"], {}).setdefault(c["kind"], 0)
        out[c["threat"]][c["kind"]] += 1
    return out
