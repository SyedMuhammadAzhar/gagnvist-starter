#!/bin/bash -l
# Fine-tuning for the GAGNVÍST hackathon, submitted by `gagnvist lumi finetune` (or
# `gagnvist jureca finetune`: the lines that differ between the two supercomputers come
# from gagnvist/clusters/).
#
# Trains a LoRA adapter for the model in {{model_path}} on the conversations in
# {{run_folder}}/train.jsonl, and saves it in {{run_folder}}/adapter.
# The training script (finetune_lora.py) is part of this job script, below, so that
# nothing in the shared project folders can change what runs. An adapter is small
# (tens of megabytes); serve it together with its model:
#
#     gagnvist lumi start chat <model> --adapter {{run_name}}
#
#SBATCH --job-name=gagnvist-finetune
#SBATCH --account={{project}}
#SBATCH --partition={{partition}}
#SBATCH --nodes=1
#SBATCH --ntasks=1
{{gpu_request}}
#SBATCH --cpus-per-task={{cpus}}
#SBATCH --time={{hours}}:00:00

{{modules}}
set -euo pipefail

# The adapter can be read by your teammates but changed by you only. The working files
# stay on this node, in a folder that only you can open, and are removed at the end.
umask 022
work=$(mktemp -d "/tmp/gagnvist-$SLURM_JOB_ID-XXXXXX")
chmod 700 "$work"
trap 'rm -rf "$work"' EXIT

cat >"$work/finetune_lora.py" <<'GAGNVIST_END_OF_SCRIPT'
{{finetune_script}}
GAGNVIST_END_OF_SCRIPT

{{gpu_environment}}
export HF_HUB_OFFLINE=1  # use only the downloaded files: never wait for a download

srun {{container_runtime}} {{container}} python "$work/finetune_lora.py" \
    --model {{model_path}} \
    --data {{run_folder}}/train.jsonl --output {{run_folder}}/adapter \
    --epochs {{epochs}} --rank {{rank}} --learning-rate {{learning_rate}}
echo "Finished: the adapter is in {{run_folder}}/adapter"
