#!/usr/bin/env python3
"""Turn a scanner's own report into the SARIF 2.1.0 file the extension harness reads.

Used by the adapters in this folder as their last step. Stdlib only. Two modes:

  # A tool that emits JSON but no SARIF (Cisco mcp-scanner, `--format raw` envelope or `--raw` array)
  python3 scan_report_to_sarif.py cisco-mcp <raw.json> <out.sarif> [--tools-file F] [--prompts-file F]
      [--resources-file F] [--asset-root DIR] [--require-analyzer llm ...] [--allow-empty]
      [--allow-incomplete] [--meta key=value ...]

  # A tool that already emits SARIF: check it, put the severity on the harness scale, tidy paths
  python3 scan_report_to_sarif.py normalize <in.sarif> <out.sarif>
      --tool skillspector|cisco-skill-scanner|aig-skill-scan|aig-mcp-scan
      [--asset-root DIR] [--allow-incomplete] [--meta key=value ...]

Every result leaves with a rule id, a file location, `properties.severity` on the harness scale
(critical | high | medium | low | info) and the tool's own value in `properties.original_severity`.
The severity tables below are the whole mapping; nothing is inferred from message text.

Exit codes: 0 written · 2 the input is not the report this mode expects (nothing is written) ·
3 the report says the scan did not finish or a requested analyzer did not run (nothing is written
unless --allow-incomplete). A scan that failed must never be read as a clean asset, so on 2 and 3
the output file is removed if it existed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = "https://docs.oasis-open.org/sarif/sarif/v2.1.0/os/schemas/sarif-schema-2.1.0.json"
HARNESS_SEVERITIES = ("critical", "high", "medium", "low", "info")
SARIF_LEVEL = {"critical": "error", "high": "error", "medium": "warning", "low": "note", "info": "note"}
LEVEL_SEVERITY = {"error": "high", "warning": "medium", "note": "low", "none": "info"}

# Each tool's own severity vocabulary -> harness scale. Keys are compared case-insensitively.
# Sources: the tools' severity enums and SARIF formatters at the versions named in README.md.
SEVERITY_MAPS = {
    # NVIDIA SkillSpector: Severity enum LOW | MEDIUM | HIGH | CRITICAL.
    "skillspector": {"critical": "critical", "high": "high", "medium": "medium", "low": "low"},
    # Cisco skill-scanner: Severity enum CRITICAL | HIGH | MEDIUM | LOW | INFO | SAFE.
    "cisco-skill-scanner": {"critical": "critical", "high": "high", "medium": "medium", "low": "low",
                            "info": "info", "safe": "info"},
    # Cisco mcp-scanner: HIGH | MEDIUM | LOW | INFO per analyzer and item (no CRITICAL level).
    # SAFE yields no result. UNKNOWN on findings means the tool did not rate them: the harness
    # default for an unrated finding is medium.
    "cisco-mcp-scanner": {"high": "high", "medium": "medium", "low": "low", "info": "info",
                          "unknown": "medium"},
    # Tencent aig-skill-scan / aig-mcp-scan: free-text level written by the model, in English or
    # Chinese. These are the values the tools' own SARIF formatters recognise.
    "aig": {"critical": "critical", "严重": "critical", "high": "high", "高危": "high",
            "medium": "medium", "中危": "medium", "low": "low", "低危": "low",
            "info": "info", "informational": "info"},
}
# normalize profiles: expected SARIF driver name and severity table.
PROFILES = {
    "skillspector": {"driver": "skillspector", "severity": "skillspector"},
    "cisco-skill-scanner": {"driver": "skill-scanner", "severity": "cisco-skill-scanner"},
    "aig-skill-scan": {"driver": "aig-skill-scan", "severity": "aig"},
    "aig-mcp-scan": {"driver": "aig-mcp-scan", "severity": "aig"},
}
# mcp-scanner analyzers whose result key is known. A requested analyzer missing from an item's
# findings means it did not run (the tool falls back without failing when a key is absent).
MCP_ANALYZER_KEYS = {"yara": "yara_analyzer", "llm": "llm_analyzer", "api": "api_analyzer",
                     "behavioral": "behavioral_analyzer"}


class Malformed(Exception):
    """The input is not the report this mode expects."""


class Incomplete(Exception):
    """The report itself says the scan did not finish, or a requested analyzer did not run."""


def load_json(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise Malformed(f"cannot read {path}: {e}") from e
    if not text.strip():
        raise Malformed(f"{path} is empty")
    try:
        return json.loads(text)
    except ValueError as e:
        raise Malformed(f"{path} is not JSON: {e}") from e


def parse_meta(pairs) -> dict:
    meta = {}
    for p in pairs or []:
        if "=" not in p:
            raise Malformed(f"--meta expects key=value, got {p!r}")
        k, v = p.split("=", 1)
        meta[k] = v
    return meta


def rel_uri(uri: str, asset_root: str | None) -> str:
    """Make a location relative to the scanned asset when it is given as an absolute path."""
    u = uri or ""
    if u.startswith("file://"):
        u = u[len("file://"):]
    if asset_root:
        root = asset_root.rstrip("/")
        if u == root:
            return "."
        if u.startswith(root + "/"):
            u = u[len(root) + 1:]
    return u or "."


def find_line(path: Path | None, name: str) -> int | None:
    """1-based line of the first line holding the JSON-encoded item name, if the file has it."""
    if not path or not name:
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for needle in (json.dumps(name, ensure_ascii=False), json.dumps(name)):
        for i, line in enumerate(lines, 1):
            if needle in line:
                return i
    return None


# ---------------------------------------------------------------- Cisco mcp-scanner JSON -> SARIF
def _mcp_item(r: dict) -> tuple[str, str]:
    kind = str(r.get("item_type") or "item")
    name = (r.get("tool_name") or r.get("prompt_name") or r.get("resource_uri")
            or r.get("resource_name") or "")
    return kind, str(name)


def convert_cisco_mcp(doc, *, sources: dict, asset_root: str | None, require: list[str],
                      allow_incomplete: bool, meta: dict, allow_empty: bool = False) -> dict:
    if isinstance(doc, dict):
        results_in = doc.get("scan_results")
        requested = doc.get("requested_analyzers") or []
        if not isinstance(results_in, list):
            raise Malformed("mcp-scanner report has no 'scan_results' list "
                            "(expected the `--format raw` envelope or the `--raw` array)")
    elif isinstance(doc, list):
        results_in, requested = doc, []
    else:
        raise Malformed("mcp-scanner report must be a JSON object or array")
    if not isinstance(requested, list):
        raise Malformed("'requested_analyzers' must be a list")
    needed = {MCP_ANALYZER_KEYS[a] for a in list(requested) + list(require) if a in MCP_ANALYZER_KEYS}
    unknown_req = [a for a in require if a not in MCP_ANALYZER_KEYS]
    if unknown_req:
        raise Malformed(f"--require-analyzer knows {sorted(MCP_ANALYZER_KEYS)}, not {unknown_req}")

    sev_map = SEVERITY_MAPS["cisco-mcp-scanner"]
    problems: list[str] = []
    if not results_in and not allow_empty:
        # mcp-scanner drops an item whose analysis it could not use (seen with the behavioral
        # mode and an unusable model reply) and still exits 0, so "no items" is not "clean".
        problems.append("the report lists no scanned item (nothing was analysed)")
    results, rules = [], {}
    for idx, r in enumerate(results_in):
        if not isinstance(r, dict) or not isinstance(r.get("findings"), dict):
            raise Malformed(f"scan_results[{idx}] has no 'findings' object")
        kind, name = _mcp_item(r)
        label = f"{kind} {name!r}"
        status = r.get("status")
        if status != "completed":
            problems.append(f"{label}: status {status!r}")
        for key in sorted(needed - set(r["findings"])):
            problems.append(f"{label}: requested analyzer {key} did not run")
        src = sources.get(kind)
        for analyzer, f in r["findings"].items():
            if not isinstance(f, dict) or "severity" not in f:
                raise Malformed(f"scan_results[{idx}].findings.{analyzer} has no 'severity'")
            if f.get("source_file"):
                # behavioral mode: the analyzer names the source file, and its summary starts
                # with "Line N:" for the function it judged.
                uri = rel_uri(str(f["source_file"]), asset_root)
                m = re.match(r"\s*Line (\d+):", str(f.get("threat_summary") or ""))
                line = int(m.group(1)) if m else None
            else:
                uri = rel_uri(str(src), asset_root) if src else "."
                line = find_line(src, name)
            if f.get("status") in ("error", "partial"):
                problems.append(f"{label}: {analyzer} status {f.get('status')!r}")
            original = str(f["severity"])
            threats = f.get("threat_names") or []
            total = f.get("total_findings") or 0
            if original.upper() == "SAFE" or (not threats and not total):
                continue
            severity = sev_map.get(original.lower())
            if severity is None:
                raise Malformed(f"{label}: {analyzer} severity {original!r} is not in the "
                                f"mcp-scanner scale {sorted(sev_map)}")
            taxonomy = [{k: t.get(k) for k in ("scanner_category", "aitech", "aisubtech")}
                        for t in f.get("mcp_taxonomies") or [] if isinstance(t, dict)]
            for threat in threats or ["UNSPECIFIED"]:
                rule_id = f"{analyzer}:{str(threat).strip().upper().replace(' ', '_')}"
                rules.setdefault(rule_id, {"id": rule_id, "shortDescription": {
                    "text": f"{threat} reported by mcp-scanner {analyzer}"}})
                phys = {"artifactLocation": {"uri": uri}}
                if line:
                    phys["region"] = {"startLine": line}
                results.append({
                    "ruleId": rule_id,
                    "level": SARIF_LEVEL[severity],
                    "message": {"text": f"{label}: {threat} ({analyzer}). "
                                        f"{f.get('threat_summary') or ''}".strip()},
                    "locations": [{"physicalLocation": phys,
                                   "logicalLocations": [{"name": name, "kind": kind}]}],
                    "properties": {
                        "severity": severity,
                        "original_severity": original,
                        # mcp-scanner reports one rolled-up severity per analyzer and item, so
                        # every threat an analyzer names on an item carries that same value.
                        "severity_scope": "analyzer-rollup",
                        "analyzer": analyzer,
                        "item_type": kind,
                        "item_name": name,
                        "analyzer_total_findings": total,
                        "taxonomy": taxonomy,
                    },
                })
    if problems and not allow_incomplete:
        raise Incomplete("mcp-scanner did not complete: " + "; ".join(problems[:8])
                         + (f" (+{len(problems) - 8} more)" if len(problems) > 8 else ""))
    return {
        "version": SARIF_VERSION, "$schema": SARIF_SCHEMA,
        "runs": [{
            "tool": {"driver": {"name": "cisco-ai-mcp-scanner",
                                "informationUri": "https://github.com/cisco-ai-defense/mcp-scanner",
                                "rules": [rules[k] for k in sorted(rules)]}},
            "invocations": [{"executionSuccessful": not problems}],
            "results": results,
            "properties": {"adapter": meta, "requested_analyzers": requested,
                           "items_scanned": len(results_in), "incomplete": problems,
                           "severity_map": sev_map},
        }],
    }


# ---------------------------------------------------------------------- native SARIF -> checked
def normalize_sarif(doc, *, tool: str, asset_root: str | None, allow_incomplete: bool,
                    meta: dict) -> dict:
    prof = PROFILES[tool]
    sev_map = SEVERITY_MAPS[prof["severity"]]
    if not isinstance(doc, dict):
        raise Malformed("SARIF must be a JSON object")
    if not str(doc.get("version", "")).startswith("2.1"):
        raise Malformed(f"not SARIF 2.1.0 (version={doc.get('version')!r})")
    runs = doc.get("runs")
    if not isinstance(runs, list) or not runs:
        raise Malformed("SARIF has no runs")
    problems: list[str] = []
    for ri, run in enumerate(runs):
        if not isinstance(run, dict) or not isinstance(run.get("results"), list):
            raise Malformed(f"runs[{ri}] has no 'results' list")
        driver = ((run.get("tool") or {}).get("driver") or {}).get("name")
        if driver != prof["driver"]:
            raise Malformed(f"runs[{ri}] was written by {driver!r}, expected {prof['driver']!r} "
                            f"for --tool {tool}")
        for inv in run.get("invocations") or []:
            if isinstance(inv, dict) and inv.get("executionSuccessful") is False:
                problems.append(f"runs[{ri}]: the tool reports executionSuccessful=false")
        note = (run.get("properties") or {}).get("scanNote")
        if note not in (None, "complete"):
            problems.append(f"runs[{ri}]: the tool reports scanNote={note!r}")
        unmapped = 0
        for xi, res in enumerate(run["results"]):
            if not isinstance(res, dict):
                raise Malformed(f"runs[{ri}].results[{xi}] is not an object")
            if not res.get("ruleId"):
                res["ruleId"] = "UNSPECIFIED"
            if not isinstance(res.get("message"), dict):
                res["message"] = {"text": str(res.get("message") or "")}
            props = res.get("properties")
            if not isinstance(props, dict):
                props = res["properties"] = {}
            original = props.get("severity")
            severity = sev_map.get(str(original).strip().lower()) if original is not None else None
            source = "tool-severity"
            if severity is None:  # the tool gave no value on its documented scale: use its level
                severity = LEVEL_SEVERITY.get(str(res.get("level") or "warning"), "medium")
                source = "sarif-level"
                unmapped += 1
            props["severity"] = severity
            props["original_severity"] = original
            props["severity_source"] = source
            locs = res.get("locations")
            if not isinstance(locs, list) or not locs:
                locs = res["locations"] = [{"physicalLocation": {"artifactLocation": {"uri": "."}}}]
            for loc in locs:
                art = (loc.setdefault("physicalLocation", {})).setdefault("artifactLocation", {})
                art["uri"] = rel_uri(str(art.get("uri") or ""), asset_root)
        rp = run.get("properties")
        if not isinstance(rp, dict):
            rp = run["properties"] = {}
        rp["adapter"] = meta
        rp["severity_map"] = sev_map
        rp["severity_from_level"] = unmapped
        rp["incomplete"] = [p for p in problems if p.startswith(f"runs[{ri}]")]
    if problems and not allow_incomplete:
        raise Incomplete(f"{tool} did not complete: " + "; ".join(problems[:8]))
    return doc


def write_out(doc: dict, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("input", type=Path)
    common.add_argument("output", type=Path)
    common.add_argument("--asset-root", default=None,
                        help="directory that was scanned; absolute locations under it become relative")
    common.add_argument("--allow-incomplete", action="store_true",
                        help="write the SARIF even when the report says the scan did not finish")
    common.add_argument("--meta", action="append", default=[], metavar="KEY=VALUE",
                        help="recorded under runs[].properties.adapter (adapter name, config, version)")
    m = sub.add_parser("cisco-mcp", parents=[common], help="Cisco mcp-scanner raw JSON -> SARIF")
    m.add_argument("--tools-file", type=Path, default=None)
    m.add_argument("--prompts-file", type=Path, default=None)
    m.add_argument("--resources-file", type=Path, default=None)
    m.add_argument("--require-analyzer", action="append", default=[], metavar="NAME",
                   help="fail unless this analyzer ran on every item (yara|llm|api|behavioral)")
    m.add_argument("--allow-empty", action="store_true",
                   help="accept a report that lists no scanned item (default: incomplete scan)")
    n = sub.add_parser("normalize", parents=[common], help="check and normalise a tool's own SARIF")
    n.add_argument("--tool", required=True, choices=sorted(PROFILES))
    a = ap.parse_args(argv)
    try:
        meta = parse_meta(a.meta)
        doc = load_json(a.input)
        if a.mode == "cisco-mcp":
            sources = {"tool": a.tools_file, "prompt": a.prompts_file, "resource": a.resources_file}
            out = convert_cisco_mcp(doc, sources=sources, asset_root=a.asset_root,
                                    require=a.require_analyzer, allow_incomplete=a.allow_incomplete,
                                    meta=meta, allow_empty=a.allow_empty)
        else:
            out = normalize_sarif(doc, tool=a.tool, asset_root=a.asset_root,
                                  allow_incomplete=a.allow_incomplete, meta=meta)
    except (Malformed, Incomplete) as e:
        a.output.unlink(missing_ok=True)
        code = 2 if isinstance(e, Malformed) else 3
        print(f"scan_report_to_sarif: {'malformed input' if code == 2 else 'incomplete scan'}: {e}",
              file=sys.stderr)
        return code
    write_out(out, a.output)
    n_res = sum(len(r["results"]) for r in out["runs"])
    print(f"scan_report_to_sarif: {n_res} result(s) -> {a.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
