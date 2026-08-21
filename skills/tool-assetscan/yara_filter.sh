#!/usr/bin/env bash
# Held-out gate (design §6): keep only mutated positives that Cisco's YARA rules canNOT match
# (0 hits), so the stratum measures the LLM-judge's value beyond signatures.
#   bash yara_filter.sh <rules-file-or-dir> <sample-path>   -> prints KEEP/DROP + hit count; exit 0 if KEEP
set -euo pipefail
rules="${1:?yara rules}"; sample="${2:?sample path}"
command -v yara >/dev/null || { echo "yara not installed (brew install yara / pip install yara-python's CLI)" >&2; exit 2; }
args=(-r); [ -d "$rules" ] && rulefiles=$(find "$rules" -name '*.yar' -o -name '*.yara') || rulefiles="$rules"
hits=0
for rf in $rulefiles; do n=$(yara "${args[@]}" "$rf" "$sample" 2>/dev/null | wc -l | tr -d ' '); hits=$((hits+n)); done
if [ "$hits" -eq 0 ]; then echo "KEEP $sample (0 YARA hits)"; exit 0; else echo "DROP $sample ($hits YARA hits — signature-detectable)"; exit 1; fi
