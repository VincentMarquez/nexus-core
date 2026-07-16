#!/usr/bin/env bash
# Official SWE-bench Pro gold-patch evaluation (Scale harness, local Docker).
# Proves the harness works; gold should resolve ~100% on the chosen instance(s).
set -euo pipefail
PRO_OS="${SWE_PRO_OS:-$HOME/SWE-bench_Pro-os}"
OUT="${1:-$HOME/nexus-core/.nexus_state/swe_pro/official}"
cd "$PRO_OS"
source .venv/bin/activate
python swe_bench_pro_eval.py \
  --raw_sample_path="$OUT/raw_sample_1.jsonl" \
  --patch_path="$OUT/gold_patch_1.json" \
  --output_dir="$OUT/gold_eval_out" \
  --scripts_dir=run_scripts \
  --num_workers=1 \
  --dockerhub_username=jefzda \
  --use_local_docker \
  --docker_platform=linux/amd64
echo "Results: $OUT/gold_eval_out/eval_results.json"
