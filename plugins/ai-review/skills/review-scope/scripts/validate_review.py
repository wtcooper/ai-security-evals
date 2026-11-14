#!/usr/bin/env python3
"""Validate a review profile (review.json) and print what is missing. Stdlib only.

    python scripts/validate_review.py review.json            # exit 0 complete, 1 errors or gaps
    python scripts/validate_review.py review.json --json     # the same findings as JSON
    python scripts/validate_review.py review.json --strict   # "unknown" answers also exit 1
    python scripts/validate_review.py --blank agent          # print an empty profile to fill in

Three kinds of finding, kept apart because they mean different things:

  error    the file breaks the schema (wrong type, a value outside a closed list, a key in
           `context` that measurement skills do not know). Fix the file.
  missing  a required answer is absent or empty. Ask the requester.
  unknown  the answer is the literal string "unknown". That is a valid, honest answer; it is
           listed so the report can carry it as not assessed.

This script checks that the scope is written down. It does not judge the scope.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from evalkit import CONTEXT_KEYS  # noqa: E402  (the keys measurement skills copy into manifests)

SCHEMA_VERSION = 1
SUBJECT_TYPES = ("model", "agent", "app", "decision-model", "voice-model", "image-model",
                 "feature")
FEATURES = ("computer-use", "memory", "connectors", "code-execution", "multi-agent",
            "background-agent", "other")
# Subject types that are, or wrap, a model whose weights may be downloadable.
WEIGHT_TYPES = ("model", "agent", "decision-model", "voice-model", "image-model")
NO_HARNESS = ("none", "n/a", "bare api")
UNKNOWN = "unknown"

_MISSING = object()


def _get(doc, dotted: str):
    cur = doc
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def _is_unknown(value) -> bool:
    return isinstance(value, str) and value.strip().lower() == UNKNOWN


def _empty(value) -> bool:
    return value is _MISSING or value is None or (isinstance(value, str) and not value.strip())


def _is_date(value) -> bool:
    try:
        dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        return False
    return True


class Findings:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.missing: list[str] = []
        self.unknown: list[str] = []
        self.warnings: list[str] = []

    def text(self, value, label: str, required: bool = True) -> str | None:
        """A non-empty string. Returns it, or None after recording why not."""
        if _empty(value):
            if required:
                self.missing.append(label)
            return None
        if not isinstance(value, str):
            self.errors.append(f"{label}: must be a string, got {type(value).__name__}")
            return None
        if _is_unknown(value):
            self.unknown.append(label)
        return value

    def choice(self, value, label: str, allowed: tuple, required: bool = True) -> str | None:
        value = self.text(value, label, required)
        if value is not None and not _is_unknown(value) and value not in allowed:
            self.errors.append(f"{label}: {value!r} is not one of {list(allowed)}")
            return None
        return value

    def date(self, value, label: str) -> None:
        value = self.text(value, label)
        if value is not None and not _is_unknown(value) and not _is_date(value):
            self.errors.append(f"{label}: {value!r} is not a YYYY-MM-DD date")

    def flag(self, value, label: str):
        """true, false or "unknown"."""
        if _empty(value):
            self.missing.append(label)
            return None
        if _is_unknown(value):
            self.unknown.append(label)
            return UNKNOWN
        if not isinstance(value, bool):
            self.errors.append(f'{label}: must be true, false or "unknown"')
            return None
        return value

    def strings(self, value, label: str) -> list | None:
        """A list of strings. An empty list is an answer ("none"); an absent key is not."""
        if value is _MISSING or value is None:
            self.missing.append(label)
            return None
        if _is_unknown(value):
            self.unknown.append(label)
            return None
        if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
            self.errors.append(f'{label}: must be a list of non-empty strings ([] means none), '
                               'or "unknown"')
            return None
        return value


def validate(doc) -> Findings:
    f = Findings()
    if not isinstance(doc, dict):
        f.errors.append("top level must be a JSON object")
        return f

    def at(path: str):
        return _get(doc, path)

    if doc.get("schema_version") != SCHEMA_VERSION:
        f.errors.append(f"schema_version: must be {SCHEMA_VERSION}")
    for path in ("review_id", "requested_by", "reviewer"):
        f.text(at(path), path)
    f.date(at("opened"), "opened")

    # --- subject ---------------------------------------------------------------------
    stype = f.choice(at("subject.type"), "subject.type", SUBJECT_TYPES)
    for path in ("subject.name", "subject.version", "subject.vendor"):
        f.text(at(path), path)
    f.choice(at("subject.feature"), "subject.feature", FEATURES, required=stype == "feature")
    if stype in WEIGHT_TYPES:
        if f.flag(at("subject.weights.open"), "subject.weights.open") is True:
            f.text(at("subject.weights.repo"), "subject.weights.repo")

    # --- context: exactly the keys measurement skills copy -----------------------------
    ctx = at("context")
    if ctx is _MISSING or ctx is None:
        f.missing.append("context")
        ctx = None
    elif not isinstance(ctx, dict):
        f.errors.append("context: must be an object")
        ctx = None
    else:
        for key in ctx:
            if key not in CONTEXT_KEYS:
                f.errors.append(f"context.{key}: not a context key; allowed keys are "
                                f"{list(CONTEXT_KEYS)}")
        for key in ("surface", "harness", "system_prompt", "data_sensitivity", "autonomy"):
            f.text(ctx.get(key), f"context.{key}")
        f.strings(ctx.get("tools"), "context.tools")
        safeguards = ctx.get("safeguards")
        if _empty(safeguards) or safeguards in ([], {}):
            f.missing.append("context.safeguards")
        elif not isinstance(safeguards, (str, list, dict)):
            f.errors.append("context.safeguards: must be a string, a list or an object")
        elif _is_unknown(safeguards):
            f.unknown.append("context.safeguards")
        harness = ctx.get("harness")
        if isinstance(harness, str) and harness.strip().lower() not in NO_HARNESS \
                and not _is_unknown(harness):
            f.text(ctx.get("harness_version"), "context.harness_version")
        f.text(ctx.get("notes"), "context.notes", required=False)

    # --- who controls each input channel -----------------------------------------------
    channels = at("input_channels")
    if channels is _MISSING or channels is None or channels == []:
        f.missing.append("input_channels (at least one: the channel the user types or speaks into)")
        channels = None
    elif not isinstance(channels, list) or not all(isinstance(c, dict) for c in channels):
        f.errors.append("input_channels: must be a list of objects")
        channels = None
    else:
        for i, chan in enumerate(channels):
            f.text(chan.get("channel"), f"input_channels[{i}].channel")
            f.text(chan.get("controlled_by"), f"input_channels[{i}].controlled_by")
            f.flag(chan.get("untrusted"), f"input_channels[{i}].untrusted")

    # --- what it can do ----------------------------------------------------------------
    can_do = None
    if at("capabilities") in (_MISSING, None):
        f.missing.append("capabilities")
    else:
        f.strings(at("capabilities.can_read"), "capabilities.can_read")
        can_do = f.strings(at("capabilities.can_do"), "capabilities.can_do")
        f.text(at("capabilities.approval"), "capabilities.approval")
        f.flag(at("capabilities.memory"), "capabilities.memory")

    # --- what happens on failure -------------------------------------------------------
    if at("failure_impact") in (_MISSING, None):
        f.missing.append("failure_impact")
    else:
        for key in ("worst_case", "affected", "detection"):
            f.text(at(f"failure_impact.{key}"), f"failure_impact.{key}")
        f.flag(at("failure_impact.reversible"), "failure_impact.reversible")

    # --- time budget -------------------------------------------------------------------
    if at("time_budget") in (_MISSING, None):
        f.missing.append("time_budget")
    else:
        f.date(at("time_budget.decision_due"), "time_budget.decision_due")
        hours = at("time_budget.hours_available")
        if _empty(hours):
            f.missing.append("time_budget.hours_available")
        elif _is_unknown(hours):
            f.unknown.append("time_budget.hours_available")
        elif isinstance(hours, bool) or not isinstance(hours, (int, float)) or hours <= 0:
            f.errors.append('time_budget.hours_available: must be a positive number or "unknown"')

    # --- what the requester ruled out, said out loud -----------------------------------
    out = at("out_of_scope")
    if out is _MISSING or out is None:
        f.missing.append("out_of_scope ([] if nothing was ruled out)")
    elif not isinstance(out, list) or not all(
            isinstance(o, dict) and isinstance(o.get("item"), str) and o["item"].strip()
            and isinstance(o.get("reason"), str) and o["reason"].strip() for o in out):
        f.errors.append("out_of_scope: must be a list of {item, reason} objects, both non-empty")

    # --- cross-field consistency (warnings: worth a question, not a schema break) -------
    tools = ctx.get("tools") if ctx else None
    if isinstance(tools, list) and not tools and can_do:
        f.warnings.append("context.tools is [] but capabilities.can_do lists actions: which "
                          "tools perform them?")
    if channels and all(c.get("untrusted") is False for c in channels):
        f.warnings.append("every input channel is marked trusted: confirm that no document, "
                          "web page, tool result or other third-party content reaches the model")
    return f


def blank(subject_type: str = "") -> dict:
    """An empty profile. `context` carries exactly the keys measurement skills read."""
    return {
        "schema_version": SCHEMA_VERSION,
        "review_id": "", "requested_by": "", "reviewer": "", "opened": "",
        "subject": {"type": subject_type, "name": "", "version": "", "vendor": "",
                    "feature": None, "weights": {"open": None, "repo": None}},
        "context": {k: None for k in CONTEXT_KEYS},
        "input_channels": [{"channel": "", "controlled_by": "", "untrusted": None, "notes": ""}],
        "capabilities": {"can_read": None, "can_do": None, "approval": "", "memory": None},
        "failure_impact": {"worst_case": "", "affected": "", "reversible": None, "detection": ""},
        "time_budget": {"decision_due": "", "hours_available": None, "notes": ""},
        "out_of_scope": None,
    }


def report(doc, f: Findings) -> str:
    subject = doc.get("subject", {}) if isinstance(doc, dict) else {}
    head = f"{doc.get('review_id') or '(no review_id)'} — {subject.get('type') or '?'} " \
           f"\"{subject.get('name') or '?'}\"" if isinstance(doc, dict) else "(unreadable)"
    lines = [f"review profile: {head}"]
    for title, items, hint in (
            ("errors", f.errors, "the file breaks the schema"),
            ("missing", f.missing, "ask the requester"),
            ("stated as unknown", f.unknown, "valid; carry into the report as not assessed"),
            ("warnings", f.warnings, "worth a question")):
        if items:
            lines.append(f"{title} ({len(items)}) — {hint}:")
            lines += [f"  - {item}" for item in items]
    if not f.errors and not f.missing:
        lines.append("complete: every required answer is present"
                     + (" (some are \"unknown\")." if f.unknown else "."))
    else:
        lines.append("incomplete: do not start the threat model or any measurement from this file.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("review", nargs="?", help="path to review.json")
    p.add_argument("--json", action="store_true", help="print findings as JSON")
    p.add_argument("--strict", action="store_true", help='treat "unknown" answers as gaps')
    p.add_argument("--blank", nargs="?", const="", metavar="TYPE",
                   help="print an empty profile (optionally with subject.type set) and exit")
    args = p.parse_args(argv)
    if args.blank is not None:
        if args.blank and args.blank not in SUBJECT_TYPES:
            p.error(f"--blank type must be one of {list(SUBJECT_TYPES)}")
        print(json.dumps(blank(args.blank), indent=2))
        return 0
    if not args.review:
        p.error("give the path to review.json, or --blank")
    try:
        doc = json.loads(Path(args.review).read_text())
    except OSError as exc:
        print(f"cannot read {args.review}: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"{args.review} is not valid JSON: {exc}", file=sys.stderr)
        return 2
    f = validate(doc)
    if args.json:
        print(json.dumps({"errors": f.errors, "missing": f.missing, "unknown": f.unknown,
                          "warnings": f.warnings,
                          "complete": not f.errors and not f.missing}, indent=2))
    else:
        print(report(doc, f))
    bad = f.errors or f.missing or (args.strict and f.unknown)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
