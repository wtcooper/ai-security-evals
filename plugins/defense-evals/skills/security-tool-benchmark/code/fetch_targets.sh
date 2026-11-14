#!/usr/bin/env bash
# Fetch detection-benchmark targets at pinned commits (design doc §4.1) into <EXP>/targets/ and
# write ground_truth.jsonl per benchmark in the match.py contract. Verifies availability first —
# several sets are new/rolling; anything missing is reported, not silently skipped.
#
#   bash fetch_targets.sh <EXP> <benchmark> [--ref <sha|tag>] [--cutoff YYYY-MM-DD] [--limit N]
#     benchmarks: livecvebench | realvuln | cwe-bench-java | cybergym-e2e | dvaa | dvmcp
#
# Each benchmark gets targets/<benchmark>/{README-fetch.md, ground_truth.jsonl, <items>/...}.
# livecvebench: only entries with disclosure date > --cutoff (the scanned model's cutoff) are kept
# and both vulnerable + fixed snapshots are materialised (recall on vulnerable, FP on fixed).
set -euo pipefail
exp="${1:?usage: fetch_targets.sh <EXP> <benchmark> [--ref R] [--cutoff DATE] [--limit N]}"; bench="${2:?}"; shift 2
ref=""; cutoff=""; limit=0
while [ $# -gt 0 ]; do case "$1" in --ref) ref="$2"; shift 2;; --cutoff) cutoff="$2"; shift 2;; --limit) limit="$2"; shift 2;; *) echo "unknown $1" >&2; exit 2;; esac; done
here="$(cd "$(dirname "$0")" && pwd)"
dst="$exp/targets/$bench"; mkdir -p "$dst"
M="python3 $here/lib/manifest.py"

clone() { # clone <url> <dir> [ref]
  local url="$1" d="$2" r="${3:-}"
  if [ ! -d "$d/.git" ]; then git clone -q "$url" "$d"; fi
  if [ -n "$r" ]; then git -C "$d" fetch -q --all --tags && git -C "$d" checkout -q "$r"; fi
  git -C "$d" rev-parse HEAD
}
record() { $M "$exp" set "benchmark.name" "\"$bench\"" >/dev/null; $M "$exp" set "benchmark.version" "\"$1\"" >/dev/null; }

case "$bench" in
  livecvebench)
    # CVE-Factory (LiveCVEBench): github.com/livecvebench/CVE-Factory — rolling; each task has a
    # Docker env, vulnerable commit, fix commit, validated exploit. Layout may change: we
    # discover tasks/*/task.json (or metadata.json) and normalise the fields we need.
    sha=$(clone https://github.com/livecvebench/CVE-Factory "$dst/src" "$ref"); record "$sha"
    python3 - "$dst" "$cutoff" "$limit" <<'PY'
import json,sys,glob,os
dst,cutoff,limit=sys.argv[1],sys.argv[2],int(sys.argv[3])
rows=[]; n=0
for meta in sorted(glob.glob(f"{dst}/src/**/task.json",recursive=True)+glob.glob(f"{dst}/src/**/metadata.json",recursive=True)):
    try: t=json.load(open(meta))
    except Exception: continue
    cve=t.get("cve") or t.get("cve_id") or t.get("id") or os.path.basename(os.path.dirname(meta))
    date=t.get("published") or t.get("disclosure_date") or t.get("date") or ""
    if cutoff and date and date[:10] <= cutoff: continue
    cwe=t.get("cwe") or t.get("cwe_id") or ""
    for i,loc in enumerate(t.get("locations") or t.get("vulnerable_locations") or [t]):
        rows.append({"target":cve,"id":f"{cve}-{i}","cwe":str(loc.get("cwe") or cwe).replace("CWE-",""),
                     "file":loc.get("file") or loc.get("path"),"function":loc.get("function"),"line":loc.get("line"),
                     "severity":t.get("severity"),"date":date,"repo":t.get("repo") or t.get("repository"),
                     "vuln_commit":t.get("vulnerable_commit") or t.get("vuln_commit"),"fix_commit":t.get("fix_commit") or t.get("patch_commit"),
                     "language":t.get("language")})
    n+=1
    if limit and n>=limit: break
open(f"{dst}/ground_truth.jsonl","w").write("".join(json.dumps(r)+"\n" for r in rows))
print(f"livecvebench: {n} tasks, {len(rows)} labelled locations (cutoff>{cutoff or 'none'}) -> ground_truth.jsonl")
if not rows: print("WARNING: no tasks parsed — inspect src/ layout and adjust the parser", file=sys.stderr)
PY
    cat > "$dst/README-fetch.md" <<'MD'
Materialise snapshots per task with `bash materialize.sh <task>` (clone repo at vuln_commit into
vulnerable/, at fix_commit into fixed/) — recall is scored on vulnerable/, precision (any alert at
the fixed location = FP) on fixed/. Contamination: keep only date > model cutoff (already filtered).
MD
    ;;
  realvuln)
    sha=$(clone https://github.com/kolega-ai/Real-Vuln-Benchmark "$dst/src" "$ref"); record "$sha"
    python3 - "$dst" <<'PY'
import json,sys,glob,csv
dst=sys.argv[1]; rows=[]
for f in glob.glob(f"{dst}/src/**/*.jsonl",recursive=True)+glob.glob(f"{dst}/src/**/*.json",recursive=True)+glob.glob(f"{dst}/src/**/*.csv",recursive=True):
    try:
        if f.endswith(".csv"):
            items=list(csv.DictReader(open(f)))
        elif f.endswith(".jsonl"):
            items=[json.loads(l) for l in open(f) if l.strip()]
        else:
            d=json.load(open(f)); items=d if isinstance(d,list) else d.get("labels") or d.get("findings") or []
    except Exception: continue
    for i,t in enumerate(items):
        if not isinstance(t,dict) or not (t.get("file") or t.get("path")): continue
        lab=str(t.get("label") or t.get("verdict") or "TP").upper()
        rows.append({"target":t.get("repo") or t.get("project") or f.split("/")[-2],"id":f"rv-{len(rows)}",
                     "cwe":str(t.get("cwe") or t.get("cwe_id") or "").replace("CWE-",""),"file":t.get("file") or t.get("path"),
                     "function":t.get("function"),"line":t.get("line") or t.get("start_line"),"label":lab,
                     "rationale":t.get("rationale") or t.get("reason")})
open(f"{dst}/ground_truth.jsonl","w").write("".join(json.dumps(r)+"\n" for r in rows if r["label"]=="TP"))
open(f"{dst}/fp_traps.jsonl","w").write("".join(json.dumps(r)+"\n" for r in rows if r["label"]=="FP"))
print(f"realvuln: {sum(1 for r in rows if r['label']=='TP')} TP labels, {sum(1 for r in rows if r['label']=='FP')} FP traps")
if not rows: print("WARNING: no labels parsed — inspect src/ layout", file=sys.stderr)
PY
    echo "RealVuln repos are public goats: run canary_probe + a mutate.py variant as a paired stratum (design §4.1)." > "$dst/README-fetch.md"
    ;;
  cwe-bench-java)
    sha=$(clone https://github.com/iris-sast/cwe-bench-java "$dst/src" "$ref"); record "$sha"
    python3 - "$dst" <<'PY'
import json,sys,csv,glob
dst=sys.argv[1]; rows=[]
for f in glob.glob(f"{dst}/src/data/*.csv")+glob.glob(f"{dst}/src/**/*.csv",recursive=True):
    for t in csv.DictReader(open(f)):
        cve=t.get("cve_id") or t.get("CVE") or t.get("cve"); 
        if not cve: continue
        rows.append({"target":cve,"id":f"{cve}-{len(rows)}","cwe":str(t.get("cwe_id") or t.get("CWE") or "").replace("CWE-",""),
                     "file":t.get("file") or t.get("path"),"function":t.get("method") or t.get("function"),"line":t.get("line"),
                     "project":t.get("project") or t.get("project_slug")})
open(f"{dst}/ground_truth.jsonl","w").write("".join(json.dumps(r)+"\n" for r in rows))
print(f"cwe-bench-java: {len(rows)} labelled rows (published: CodeQL 27/120, LLM-assisted 55/120)")
PY
    ;;
  cybergym-e2e)
    sha=$(clone https://github.com/sunblaze-ucb/cybergym-e2e "$dst/src" "$ref"); record "$sha"
    echo "cybergym-e2e cloned @ $sha — sample ~100 post-2025 vulnerable<->fixed pairs; write ground_truth.jsonl from its task index (crash PoC = oracle)." | tee "$dst/README-fetch.md"
    ;;
  dvaa)  sha=$(clone https://github.com/opena2a-org/damn-vulnerable-ai-agent "$dst/src" "$ref"); record "$sha"
         rm -rf "$dst/src/solutions" 2>/dev/null || true; echo "DVAA @ $sha (solutions/ removed — challenge-level ground truth only)" ;;
  dvmcp) sha=$(clone https://github.com/harishsg993010/damn-vulnerable-MCP-server "$dst/src" "$ref"); record "$sha"
         rm -rf "$dst/src/solutions" 2>/dev/null || true; echo "DVMCP @ $sha (solutions/ removed)" ;;
  *) echo "unknown benchmark $bench" >&2; exit 2;;
esac
echo "TARGETS=$dst"
