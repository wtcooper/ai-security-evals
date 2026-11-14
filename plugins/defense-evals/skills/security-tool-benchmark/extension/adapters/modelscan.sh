#!/usr/bin/env bash
# ModelScan (Protect AI) signature baseline for model files — SCAN ONLY, no-network container.
#   adapters/modelscan.sh <model-file> <out-dir>
set -euo pipefail
asset="${1:?}"; out="${2:?}"
docker run --rm --network none -v "$(cd "$(dirname "$asset")" && pwd):/in:ro" -v "$out:/out" \
  python:3.11-slim sh -c "pip install -q modelscan && modelscan -p /in/$(basename "$asset") -r json -o /out/modelscan.json" || true
python3 - "$out/modelscan.json" "$out/findings.sarif" <<'PY'
import json,sys,os
src,dst=sys.argv[1],sys.argv[2]; res=[]
if os.path.exists(src):
    d=json.load(open(src))
    for i in d.get("issues",d.get("summary",{}).get("issues_by_severity",[])) or []:
        res.append({"ruleId":str(i.get("severity","")),"message":{"text":json.dumps(i)},"level":"error"})
json.dump({"version":"2.1.0","runs":[{"tool":{"driver":{"name":"modelscan"}},"results":res}]}, open(dst,"w"))
PY
[ -f "$out/findings.sarif" ]
