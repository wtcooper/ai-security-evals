#!/usr/bin/env python3
"""Read experiment folders written by the measurement skills. Stdlib only.

An experiment folder is `<evals>/<skill>/<label>_<date>/` holding `manifest.json` and
`summary.md`, and sometimes `summary.json` and `results.json` (at the top level or under
`results/`). The measurement skills do not share one JSON shape, so this reader looks for
three things wherever they sit in those files and reports what it could not read:

  metrics   any object with a numeric `value` or `rate` plus a sample count or an interval
  flags     validity flags: objects with a `flag` key inside a list named `flags` or
            `validity_flags` (the shape evalkit.validity_flag emits)
  failures  rows whose `status` is present and not "ok"

This file is shipped, byte for byte, in both review-criteria and review-report.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

JSON_FILES = ("summary.json", "results.json", "results/summary.json", "results/results.json")
VALUE_KEYS = ("value", "rate")
N_KEYS = ("samples_completed", "graded", "n", "samples", "scored")
FLAG_LISTS = ("flags", "validity_flags")
# Headings under which a summary.md lists what should be read before any number.
VALIDITY_HEADING = re.compile(r"read (this )?(first|before)|validity|did not produce|"
                              r"not (be )?trust", re.I)
_SKIP_KEYS = ("all_metrics", "samples", "files", "limits", "validity_limits")


def find_experiments(evals_dir: str | Path) -> list[Path]:
    """Every `<evals>/<skill>/<experiment>/` that is a directory, oldest name first.
    Folders with no manifest.json are returned too, so they can be reported, not skipped."""
    root = Path(evals_dir)
    if not root.is_dir():
        return []
    return sorted(p for p in root.glob("*/*") if p.is_dir() and not p.name.startswith("."))


def _number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x


def _interval(node: dict):
    for key in ("ci95", "ci", "interval"):
        ci = node.get(key)
        if isinstance(ci, (list, tuple)) and len(ci) == 2 and all(_number(v) for v in ci):
            return [float(ci[0]), float(ci[1])]
    return None


def _as_metric(node: dict, path: tuple) -> dict | None:
    value = next((node[k] for k in VALUE_KEYS if _number(node.get(k))), None)
    if value is None:
        return None
    n = next((node[k] for k in N_KEYS if _number(node.get(k))), None)
    ci = _interval(node)
    if n is None and ci is None:
        return None                     # a bare number with no denominator is not a result
    benchmark = node.get("check") or node.get("benchmark")
    arm = node.get("arm") or node.get("model")
    parts = [str(p) for p in path if not str(p).isdigit()]
    return {
        "label": (f"{benchmark} · {arm}" if benchmark and arm else benchmark)
        or "/".join(parts) or "metric",
        "parts": sorted({*parts, *(q for p in parts for q in p.split("|")),
                         *(str(x) for x in (benchmark, arm, node.get("metric")) if x)}),
        "benchmark": benchmark, "arm": arm,
        "dimension": node.get("dimension"), "reads_as": node.get("reads_as"),
        "direction": node.get("direction"),
        "value": float(value), "n": int(n) if n is not None else None, "ci95": ci,
        "status": node.get("status"),
    }


def _walk(node, path: tuple, out: dict) -> None:
    if isinstance(node, dict):
        metric = _as_metric(node, path)
        if metric:
            out["metrics"].append(metric)
        status = node.get("status")
        if isinstance(status, str) and status != "ok" and ("check" in node or "arm" in node):
            out["failures"].append({
                "where": " / ".join(str(node[k]) for k in ("arm", "check") if node.get(k)),
                "status": status, "error": node.get("error")})
        for key, child in node.items():
            if key in FLAG_LISTS and isinstance(child, list):
                where = " / ".join(str(node[k]) for k in ("arm", "check") if node.get(k)) \
                    or "/".join(str(p) for p in path if not str(p).isdigit())
                for flag in child:
                    if isinstance(flag, dict) and flag.get("flag"):
                        scope = " / ".join(str(flag[k]) for k in ("arm", "check", "scope")
                                           if flag.get(k))
                        out["flags"].append({
                            "where": scope or where, "flag": flag["flag"],
                            "observed": flag.get("observed"), "limit": flag.get("limit"),
                            "meaning": flag.get("meaning") or ""})
                    elif isinstance(flag, str) and flag.strip():
                        out["flags"].append({"where": where, "flag": flag.strip(),
                                             "observed": None, "limit": None, "meaning": ""})
            elif key not in _SKIP_KEYS:
                _walk(child, path + (key,), out)
    elif isinstance(node, list):
        for i, child in enumerate(node):
            _walk(child, path + (i,), out)


def _dedupe(items: list[dict], keys: tuple) -> list[dict]:
    seen, out = set(), []
    for item in items:
        mark = tuple(json.dumps(item.get(k), sort_keys=True) for k in keys)
        if mark not in seen:
            seen.add(mark)
            out.append(item)
    return out


def validity_section(markdown: str) -> list[str]:
    """The lines a summary.md puts under its own 'read first' / validity heading."""
    lines, keep = [], False
    for line in markdown.split("\n"):
        heading = re.match(r"^#{1,6}\s+(.*)$", line)
        if heading:
            keep = bool(VALIDITY_HEADING.search(heading.group(1)))
            continue
        if keep and line.strip():
            lines.append(line.rstrip())
    return lines


def read_experiment(folder: str | Path) -> dict:
    """Everything the review needs from one experiment folder. Never raises on bad content:
    what could not be read is listed under `problems`."""
    folder = Path(folder)
    exp = {"path": str(folder), "skill": folder.parent.name, "experiment": folder.name,
           "label": folder.name, "created": None, "manifest": None, "context": {},
           "summary_md": None, "summary_validity_lines": [], "json_sources": [],
           "metrics": [], "flags": [], "failures": [], "problems": []}

    manifest_path = folder / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text())
        except ValueError as exc:
            exp["problems"].append(f"manifest.json is not valid JSON ({exc})")
        else:
            if isinstance(manifest, dict):
                exp["manifest"] = manifest
                exp["skill"] = manifest.get("skill") or exp["skill"]
                exp["label"] = manifest.get("label") or exp["label"]
                exp["created"] = manifest.get("created")
                ctx = manifest.get("context")
                exp["context"] = ctx if isinstance(ctx, dict) else {}
                todo = [t for t in manifest.get("_todo") or [] if isinstance(t, str)]
                if todo:
                    exp["problems"].append("manifest.json has unfilled fields: " + ", ".join(todo))
            else:
                exp["problems"].append("manifest.json is not a JSON object")
    else:
        exp["problems"].append("no manifest.json: what ran, and in which context, is not recorded")

    summary_path = folder / "summary.md"
    if summary_path.is_file():
        exp["summary_md"] = summary_path.read_text()
        exp["summary_validity_lines"] = validity_section(exp["summary_md"])
    else:
        exp["problems"].append("no summary.md: this experiment reports no result")

    found = {"metrics": [], "flags": [], "failures": []}
    for rel in JSON_FILES:
        path = folder / rel
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text())
        except ValueError as exc:
            exp["problems"].append(f"{rel} is not valid JSON ({exc})")
            continue
        exp["json_sources"].append(rel)
        _walk(data, (), found)
    exp["metrics"] = _dedupe(found["metrics"], ("benchmark", "arm", "value", "n", "ci95")) \
        if found["metrics"] else []
    exp["flags"] = _dedupe(found["flags"], ("where", "flag", "observed"))
    exp["failures"] = _dedupe(found["failures"], ("where", "status"))
    return exp


def match_metrics(exp: dict, measure: dict) -> list[dict]:
    """Metrics of an experiment that a `measure` object points at. A metric matches when the
    experiment's skill equals measure.skill (if set) and each of benchmark / metric / arm that
    is set appears among the metric's label parts."""
    if measure.get("skill") and measure["skill"] != exp["skill"]:
        return []
    wanted = [str(measure[k]) for k in ("benchmark", "metric", "arm") if measure.get(k)]
    if not wanted:
        return []
    return [m for m in exp["metrics"] if all(w in m["parts"] for w in wanted)]


def fmt_metric(metric: dict) -> str:
    """`0.930 [0.862–0.966] n=100` — the number, its 95% interval if recorded, and n."""
    text = f"{metric['value']:.3f}"
    if metric.get("ci95"):
        text += f" [{metric['ci95'][0]:.3f}–{metric['ci95'][1]:.3f}]"
    else:
        text += " [no interval recorded]"
    return text + (f" n={metric['n']}" if metric.get("n") is not None else " n not recorded")
