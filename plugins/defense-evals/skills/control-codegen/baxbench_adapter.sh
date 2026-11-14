#!/usr/bin/env bash
# P6 robustness (design §3.2.2): "generate externally, evaluate in-harness". Drop an app OUR agent
# built (on an arm branch) into BaxBench's results layout, then run only its test + evaluate modes
# so BaxBench's expert functional tests + black-box exploits score the genuine artifact. Correct &
# Secure is the metric. Keep everything but the pre-build diff constant across arms.
#   bash baxbench_adapter.sh <baxbench-dir> <model-id> <scenario> <env> <arm> <sample> <app-dir> [--temperature 0.4]
set -euo pipefail
bax="${1:?baxbench checkout}"; model="${2:?}"; scenario="${3:?}"; env="${4:?}"; arm="${5:?}"; i="${6:?}"; app="${7:?built app dir}"; shift 7
temp="0.4"; while [ $# -gt 0 ]; do case "$1" in --temperature) temp="$2"; shift 2;; *) echo "unknown $1" >&2; exit 2;; esac; done
prompt="$arm"     # arm label doubles as the BaxBench prompt tag (none/generic/specific≈A/B/E)
dest="$bax/results/$model/$scenario/$env/temp${temp}-spec-${prompt}/sample${i}/code"
mkdir -p "$dest"; cp -R "$app"/. "$dest"/
echo "placed $app -> $dest"
echo "now: cd $bax && pipenv run python src/main.py --models $model --mode test --n_samples $((i)) && \\"
echo "         pipenv run python src/main.py --models $model --mode evaluate --n_samples $((i)) --ks 1 5"
