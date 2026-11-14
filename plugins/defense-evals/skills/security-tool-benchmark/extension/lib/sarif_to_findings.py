#!/usr/bin/env python3
"""Normalise scanner output (SARIF 2.1 or GitHub code-scanning alerts JSON) into the
shared findings.jsonl contract (design doc §2.3), one row per finding:

  {run, arm, target, sample, spec, tool, tool_run, rule_id, cwe, cwe_family, file, line,
   severity, confidence, oracle_confirmed, exploitable, ground_truth_id, matched, message}

  python3 sarif_to_findings.py codeql.sarif --tool codeql --run EXP --arm A --target spec-01 --sample 1 \
      --append <EXP>/findings.jsonl
  python3 sarif_to_findings.py alerts.json --format gh-alerts --tool codeql ...
  python3 sarif_to_findings.py llm-scan.sarif --tool scan-code --tool-run 2 ...

CWE resolution order: CodeQL rule tags `external/cwe/cwe-NNN` -> Semgrep `properties.cwe`
-> free text (rule category / message) via cwe_map.cwe_from_text -> "uncwe".
Severity: `security-severity` score (>=9 critical, >=7 high, >=4 medium, else low)
-> `properties.severity` -> SARIF level (error=high, warning=medium, note=low).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cwe_map import cwe_from_text, family_of  # noqa: E402

FIELDS = ["run", "arm", "target", "sample", "spec", "tool", "tool_run", "rule_id", "cwe",
          "cwe_family", "file", "line", "severity", "confidence", "oracle_confirmed",
          "exploitable", "ground_truth_id", "matched", "message"]
LEVEL_SEV = {"error": "high", "warning": "medium", "note": "low", "none": "info"}
SEVERITIES = ("critical", "high", "medium", "low", "info")


def severity_from_score(score) -> str | None:
    try:
        s = float(score)
    except (TypeError, ValueError):
        return None
    if s >= 9.0:
        return "critical"
    if s >= 7.0:
        return "high"
    if s >= 4.0:
        return "medium"
    return "low"


def _tags_cwe(tags) -> str | None:
    for t in tags or []:
        c = cwe_from_text(str(t)) if "cwe" in str(t).lower() else None
        if c:
            return c
    return None


def _prop_cwe(props: dict) -> str | None:
    v = props.get("cwe")
    if not v:
        return None
    if isinstance(v, list):
        v = v[0] if v else None
    return cwe_from_text(str(v)) if v else None


def _strip(path: str, prefix: str | None) -> str:
    if prefix and path.startswith(prefix):
        path = path[len(prefix):]
    return path.lstrip("/")


def _row(ctx: dict, **kw) -> dict:
    row = {k: None for k in FIELDS}
    row.update({k: ctx[k] for k in ("run", "arm", "target", "sample", "spec", "tool", "tool_run")})
    row.update(kw)
    row["cwe_family"] = family_of(row["cwe"]) if row["cwe"] else "uncwe"
    row["cwe"] = row["cwe"] or "uncwe"
    if row["severity"] not in SEVERITIES:
        row["severity"] = "medium"
    return row


def iter_sarif(doc: dict, ctx: dict, strip_prefix: str | None = None):
    for run in doc.get("runs", []):
        rules = {}
        for r in run.get("tool", {}).get("driver", {}).get("rules", []) or []:
            rules[r.get("id")] = r
        for ext in run.get("tool", {}).get("extensions", []) or []:
            for r in ext.get("rules", []) or []:
                rules.setdefault(r.get("id"), r)
        for res in run.get("results", []) or []:
            rid = res.get("ruleId") or ""
            rule = rules.get(rid, {})
            rprops = rule.get("properties", {}) or {}
            props = res.get("properties", {}) or {}
            msg = (res.get("message", {}) or {}).get("text", "") or ""
            cwe = (_tags_cwe(rprops.get("tags")) or _prop_cwe(rprops) or _prop_cwe(props)
                   or _tags_cwe(props.get("tags"))
                   or cwe_from_text(" ".join(str(x) for x in (
                       rprops.get("category"), props.get("category"), rule.get("name"),
                       (rule.get("shortDescription") or {}).get("text"), rid, msg) if x)))
            sev = (severity_from_score(rprops.get("security-severity") or props.get("security-severity"))
                   or (str(props.get("severity") or "").lower() or None)
                   or LEVEL_SEV.get(res.get("level") or (rule.get("defaultConfiguration") or {}).get("level") or "warning"))
            loc = ((res.get("locations") or [{}])[0].get("physicalLocation") or {})
            yield _row(ctx, rule_id=rid, cwe=cwe,
                       file=_strip((loc.get("artifactLocation") or {}).get("uri", "") or "", strip_prefix),
                       line=(loc.get("region") or {}).get("startLine"),
                       severity=sev, confidence=props.get("confidence") or None,
                       message=msg[:500])


def iter_gh_alerts(alerts: list, ctx: dict, strip_prefix: str | None = None, include_closed=False):
    for a in alerts:
        if not include_closed and a.get("state") not in (None, "open"):
            continue
        rule = a.get("rule", {}) or {}
        inst = a.get("most_recent_instance", {}) or {}
        loc = inst.get("location", {}) or {}
        cwe = _tags_cwe(rule.get("tags")) or cwe_from_text(" ".join(
            str(x) for x in (rule.get("id"), rule.get("description"), (inst.get("message") or {}).get("text")) if x))
        sev = (str(rule.get("security_severity_level") or "").lower() or None) or \
            {"error": "high", "warning": "medium", "note": "low"}.get(rule.get("severity"), "medium")
        yield _row(ctx, rule_id=rule.get("id"), cwe=cwe,
                   file=_strip(loc.get("path", "") or "", strip_prefix), line=loc.get("start_line"),
                   severity=sev, message=((inst.get("message") or {}).get("text") or "")[:500])


def convert(path: Path, fmt: str, ctx: dict, strip_prefix=None) -> list[dict]:
    doc = json.loads(path.read_text())
    if fmt == "gh-alerts":
        return list(iter_gh_alerts(doc if isinstance(doc, list) else doc.get("alerts", []), ctx, strip_prefix))
    return list(iter_sarif(doc, ctx, strip_prefix))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path)
    ap.add_argument("--format", choices=["sarif", "gh-alerts"], default="sarif")
    ap.add_argument("--tool", required=True, help="codeql | scan-code | semgrep | ...")
    ap.add_argument("--run", required=True)
    ap.add_argument("--arm", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--sample", type=int, default=1)
    ap.add_argument("--spec", default=None)
    ap.add_argument("--tool-run", type=int, default=1)
    ap.add_argument("--strip-prefix", default=None)
    ap.add_argument("--append", type=Path, default=None, help="findings.jsonl to append to (else stdout)")
    a = ap.parse_args()
    ctx = dict(run=a.run, arm=a.arm, target=a.target, sample=a.sample, spec=a.spec or a.target,
               tool=a.tool, tool_run=a.tool_run)
    rows = convert(a.input, a.format, ctx, a.strip_prefix)
    out = "".join(json.dumps(r) + "\n" for r in rows)
    if a.append:
        a.append.parent.mkdir(parents=True, exist_ok=True)
        with a.append.open("a") as fh:
            fh.write(out)
        print(f"appended {len(rows)} findings -> {a.append}", file=sys.stderr)
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
