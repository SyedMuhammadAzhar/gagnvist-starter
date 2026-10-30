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
#     gagnvist {{cluster_name}} start chat <model> --adapter {{run_name}}
#
# The organizers can end the job, although Slurm lets only you cancel it: the job ends
# itself when a file named after its job id appears in their folder of stop files (only
# they can create files there), which the loop below looks for every few seconds.
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
cleanup() {
    kill ${training:-} 2>/dev/null || true
    rm -rf "$work"
}
trap cleanup EXIT
stop_file="{{stop_folder}}/$SLURM_JOB_ID"

cat >"$work/finetune_lora.py" <<'GAGNVIST_END_OF_SCRIPT'
{{finetune_script}}
GAGNVIST_END_OF_SCRIPT

{{gpu_environment}}
{{finetune_environment}}
export HF_HUB_OFFLINE=1  # use only the downloaded files: never wait for a download

srun {{container_runtime}} {{container}} python3 "$work/finetune_lora.py" \
    --model {{model_path}} \
    --data {{run_folder}}/train.jsonl --output {{run_folder}}/adapter \
    --epochs {{epochs}} --rank {{rank}} --learning-rate {{learning_rate}} &
training=$!
while kill -0 "$training" 2>/dev/null; do
    if [ -e "$stop_file" ]; then echo "The organizers stopped this job." >&2; exit 0; fi
    sleep 5
done
wait "$training"  # the training's exit status: a failed training fails the job
echo "Finished: the adapter is in {{run_folder}}/adapter"
