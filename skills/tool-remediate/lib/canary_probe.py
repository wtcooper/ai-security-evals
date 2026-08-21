#!/usr/bin/env python3
"""Contamination controls (design doc §2.1): (1) a cold *canary recall probe* — ask the model
under test, with no context, to recite the vulnerabilities / flag route of a target; if it can,
the target is `contaminated`; (2) a *trace audit* — grep agent transcripts for canonical target
names/payloads appearing before any tool use (recall, not discovery).

  canary_probe.py probe --questions q.jsonl --out <EXP>/contamination/canary.json [--n 3] [--model M] [--exp <EXP>]
      q.jsonl rows: {"target": "CVE-2026-1234", "prompt": "List the vulnerabilities in ...",
                     "markers": ["regex", ...], "threshold": 1}
      contaminated := >= threshold marker hits in >= ceil(n/2) of n independent T=0 completions.
  canary_probe.py audit --transcripts <EXP>/transcripts --markers markers.txt --out <EXP>/contamination/trace_audit.json
      markers.txt: one regex per line (# comments ok). Transcripts: Claude `stream-json` .jsonl or plain text.

Endpoint (OpenAI-compatible): AISEC_GATEWAY_BASE_URL / AISEC_GATEWAY_API_KEY / AISEC_MODEL, else
LITELLM_BASE_URL / LITELLM_API_KEY (a local LiteLLM gateway on :4000). Uses only urllib (stdlib).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


def endpoint(model: str | None) -> tuple[str, str, str]:
    base = os.environ.get("AISEC_GATEWAY_BASE_URL") or os.environ.get("LITELLM_BASE_URL") or ""
    key = os.environ.get("AISEC_GATEWAY_API_KEY") or os.environ.get("LITELLM_API_KEY") or "sk-none"
    model = model or os.environ.get("AISEC_MODEL") or os.environ.get("CANARY_MODEL") or ""
    if not base or not model:
        raise SystemExit("set AISEC_GATEWAY_BASE_URL + AISEC_MODEL (or LITELLM_BASE_URL + --model)")
    return base.rstrip("/"), key, model


def complete(base: str, key: str, model: str, prompt: str, temperature: float = 0.0, timeout: int = 120) -> str:
    body = json.dumps({"model": model, "temperature": temperature,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(f"{base}/chat/completions", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        doc = json.loads(r.read().decode())
    return (doc.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""


def load_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def probe(args) -> int:
    base, key, model = endpoint(args.model)
    rows = load_jsonl(args.questions)
    results, contaminated = [], []
    for q in rows:
        pats = [re.compile(m, re.I) for m in q.get("markers", [])]
        thr = int(q.get("threshold", 1))
        runs = []
        for i in range(args.n):
            try:
                text = complete(base, key, model, q["prompt"], temperature=0.0)
            except (urllib.error.URLError, TimeoutError) as e:
                text = f"<<error: {e}>>"
            hits = sorted({p.pattern for p in pats if p.search(text)})
            runs.append({"i": i, "hits": hits, "n_hits": len(hits), "text": text[:4000]})
        positive = sum(1 for r in runs if r["n_hits"] >= thr)
        is_c = positive >= math.ceil(args.n / 2)
        results.append({"target": q["target"], "model": model, "threshold": thr, "n": args.n,
                        "positive_runs": positive, "contaminated": is_c, "runs": runs})
        if is_c:
            contaminated.append(q["target"])
        print(f"{q['target']}: {'CONTAMINATED' if is_c else 'clean'} ({positive}/{args.n} runs ≥{thr} markers)", file=sys.stderr)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"model": model, "n": args.n, "results": results,
                                    "contaminated_targets": contaminated}, indent=1) + "\n")
    if args.exp:
        sys.path.insert(0, str(Path(__file__).parent))
        import manifest as mf  # noqa
        mp = mf._mpath(str(args.exp)); doc = mf._load(mp)
        mf.set_(doc, "contamination.canary_probe", str(args.out))
        mf.set_(doc, "contamination.contaminated_targets",
                sorted(set((mf.get(doc, "contamination.contaminated_targets") or []) + contaminated)))
        mf._save(mp, doc)
    print(f"CONTAMINATED={','.join(contaminated)}")
    return 0


def _events(path: Path):
    """Yield (index, kind, text) from a Claude stream-json transcript or plain text file."""
    txt = path.read_text(errors="replace")
    idx = 0
    for line in txt.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            yield idx, "text", line
            idx += 1
            continue
        kind = "text"
        msg = ev.get("message") if isinstance(ev, dict) else None
        content = (msg or {}).get("content") if isinstance(msg, dict) else None
        if isinstance(content, list):
            for c in content:
                if c.get("type") == "tool_use":
                    kind = "tool_use"
                    yield idx, kind, json.dumps(c.get("input", ""))[:5000]
                elif c.get("type") == "text":
                    yield idx, "text", c.get("text", "")
                elif c.get("type") == "tool_result":
                    yield idx, "tool_result", json.dumps(c.get("content", ""))[:5000]
                idx += 1
            continue
        yield idx, ("tool_use" if ev.get("type") == "tool_use" else "text"), json.dumps(ev)[:5000]
        idx += 1


def audit(args) -> int:
    pats = [re.compile(l.strip(), re.I) for l in args.markers.read_text().splitlines()
            if l.strip() and not l.strip().startswith("#")]
    report = []
    files = sorted(args.transcripts.rglob("*")) if args.transcripts.is_dir() else [args.transcripts]
    for f in files:
        if not f.is_file():
            continue
        first_tool = None
        hits = []
        for idx, kind, text in _events(f):
            if kind == "tool_use" and first_tool is None:
                first_tool = idx
            if kind in ("text", "tool_use"):
                for p in pats:
                    if p.search(text):
                        hits.append({"event": idx, "kind": kind, "marker": p.pattern,
                                     "before_first_tool": first_tool is None or idx < first_tool})
        pre = [h for h in hits if h["before_first_tool"]]
        report.append({"transcript": str(f), "first_tool_event": first_tool, "hits": hits,
                       "n_hits": len(hits), "n_before_first_tool": len(pre), "suspicious": bool(pre)})
        print(f"{f.name}: {len(hits)} hits, {len(pre)} before first tool use{'  <-- SUSPICIOUS' if pre else ''}", file=sys.stderr)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"markers": [p.pattern for p in pats], "transcripts": report}, indent=1) + "\n")
    print(f"SUSPICIOUS={sum(1 for r in report if r['suspicious'])}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probe")
    p.add_argument("--questions", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--n", type=int, default=3)
    p.add_argument("--model", default=None)
    p.add_argument("--exp", type=Path, default=None)
    p.set_defaults(fn=probe)
    a = sub.add_parser("audit")
    a.add_argument("--transcripts", type=Path, required=True)
    a.add_argument("--markers", type=Path, required=True)
    a.add_argument("--out", type=Path, required=True)
    a.set_defaults(fn=audit)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
