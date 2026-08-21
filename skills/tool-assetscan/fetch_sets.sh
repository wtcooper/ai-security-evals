#!/usr/bin/env bash
# Fetch labelled asset corpora at pinned refs (design §6). Verifies availability; anything
# unresolved is reported (several sets are new — MalSkillBench release, etc.). Vendor fixtures are
# EXCLUDED (total contamination). Writes sets/<scanner>/<set>/ + labels.jsonl {asset,label,stratum}.
#   bash fetch_sets.sh <EXP> <scanner> <set>
#     scanner=mcp  set=mcptox | mcpsecbench
#     scanner=skill set=skillsieve | skillvetbench | malskillbench | ours   (ours = anthropics/skills + our repo, all benign)
#     scanner=model set=pickleball | safepickle | shadowpickle
set -euo pipefail
exp="${1:?usage: fetch_sets.sh <EXP> <scanner> <set>}"; scanner="${2:?}"; set="${3:?}"; 
here="$(cd "$(dirname "$0")" && pwd)"; dst="$exp/sets/$scanner/$set"; mkdir -p "$dst"
clone() { [ -d "$2/.git" ] || git clone -q --depth 1 "$1" "$2"; git -C "$2" rev-parse HEAD; }
warn_release() { echo "WARNING: $1 — verify the public release exists before relying on it (design §11)" >&2; }
case "$scanner/$set" in
  mcp/mcptox)       warn_release "MCPTox (arXiv 2508.14925) repo url unconfirmed"; echo "Populate $dst with the 1,312 poisoned tool descriptions + paired originals as negatives; labels.jsonl {asset,label}." > "$dst/README.md";;
  mcp/mcpsecbench)  sha=$(clone https://github.com/AIS2Lab/MCPSecBench "$dst/src"); echo "MCPSecBench @ $sha (17 attack types) — extract server dirs as positives.";;
  skill/skillsieve) sha=$(clone https://github.com/xiaohou521/skillsieve "$dst/src"); echo "SkillSieve @ $sha (89 mal / 311 benign, stealth 1–5) — read its labels into labels.jsonl.";;
  skill/skillvetbench) sha=$(clone https://github.com/supreme-lab/SkillVetBench "$dst/src"); echo "SkillVetBench @ $sha (78 mal / 22 benign, published baselines).";;
  skill/malskillbench) warn_release "MalSkillBench (arXiv 2606.07131) CC0 release unverified"; echo "3,944 malicious + 4,000 benign, sandbox-verified — populate when released." > "$dst/README.md";;
  skill/ours)       git clone -q --depth 1 https://github.com/anthropics/skills "$dst/anthropics-skills" 2>/dev/null || true
                    printf '%s\n' "Benign regression set: anthropics/skills + this repo's own skills (all label=benign)." > "$dst/README.md"
                    { for d in "$dst/anthropics-skills"/*/; do [ -d "$d" ] && printf '{"asset":"%s","label":"benign","stratum":"shipped"}\n' "$(basename "$d")"; done; } > "$dst/labels.jsonl";;
  model/pickleball) warn_release "PickleBall (zenodo 16974645) — fetch the artifact tarball manually"; echo "252 benign HF + 84 malicious; put under $dst/ with labels.jsonl." > "$dst/README.md";;
  model/safepickle) warn_release "SafePickle (arXiv 2602.19818) CC BY-NC-ND"; echo "648 benign + 79 malicious + 9 evasive + 6 real; labels.jsonl." > "$dst/README.md";;
  model/shadowpickle) warn_release "ShadowPickle (arXiv 2607.17503)"; echo "3,000 mal + 3,000 benign evasion set (PickleScan/ModelScan recall 0.0)." > "$dst/README.md";;
  *) echo "unknown scanner/set: $scanner/$set" >&2; exit 2;;
esac
echo "SET=$dst"; [ -f "$dst/labels.jsonl" ] && echo "LABELS=$(wc -l < "$dst/labels.jsonl") assets" || echo "LABELS=(write $dst/labels.jsonl from the set's manifest)"
