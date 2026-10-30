#!/bin/bash -l
# A model server for the GAGNVÍST hackathon, submitted by `gagnvist lumi start` (or
# `gagnvist jureca start`: the lines that differ between the two supercomputers come
# from gagnvist/clusters/).
#
# vLLM serves the model in {{model_path}} on {{gpus}} GPU(s), under
# the name "{{request_name}}". It listens on a socket file that only your account can
# open. In front of it, a gatekeeper (key_proxy.py, written out below) listens on a
# network port for the tunnel from your computer, and lets through only requests that
# carry the job's key: a random key made for this job alone. Once the model is loaded,
# the port and the key are written to ~/.gagnvist/jobs/<job id>.json (in your home
# folder, which only you can read), where `gagnvist {{cluster_name}} connect --job <job id>`
# finds them.
#
# Cost: the job is billed, busy or idle, until it ends (LUMI: 0.5 GPU-hours per GPU chip
# per hour; JURECA: a whole node, 128 core-hours per hour).
# Stop it when you are done:  gagnvist {{cluster_name}} stop <job id>
#
# The organizers can end the job too, although Slurm lets only you cancel it: the job
# ends itself when a file named after its job id appears in their folder of stop files
# (only they can create files there), which the loops below look for every few seconds.
#
#SBATCH --job-name={{job_name}}
#SBATCH --account={{project}}
#SBATCH --partition={{partition}}
#SBATCH --nodes=1
#SBATCH --ntasks=1
{{gpu_request}}
#SBATCH --cpus-per-task={{cpus}}
#SBATCH --time={{hours}}:00:00

{{modules}}
set -euo pipefail

# Everything this job writes from here on can be read by you only. Its working files
# stay on this node, in a folder that only you can open, and are removed at the end.
umask 077
address="$HOME/.gagnvist/jobs/$SLURM_JOB_ID.json"
mkdir -p "$HOME/.gagnvist/jobs"
work=$(mktemp -d "/tmp/gagnvist-$SLURM_JOB_ID-XXXXXX")
cleanup() {
    rm -f "$address"
    kill ${server:-} ${gatekeeper:-} 2>/dev/null || true
    rm -rf "$work"
}
trap cleanup EXIT
trap 'exit 143' TERM  # stopping the job sends TERM: end, and clean up as above
stop_file="{{stop_folder}}/$SLURM_JOB_ID"

# The gatekeeper's port, and the key. The key is passed in an environment variable:
# a command-line argument could be seen by other users of this node.
port=$((20000 + RANDOM % 20000))
while (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; do port=$((20000 + RANDOM % 20000)); done
GAGNVIST_KEY=$(head -c 30 /dev/urandom | od -An -tx1 | tr -d ' \n')
export GAGNVIST_KEY

cat >"$work/key_proxy.py" <<'GAGNVIST_END_OF_SCRIPT'
{{key_proxy}}
GAGNVIST_END_OF_SCRIPT

{{gpu_environment}}
export VLLM_CACHE_ROOT="$work/vllm-cache"
export HF_HUB_OFFLINE=1  # use only the downloaded files: never wait for a download

srun {{container_runtime}} {{container}} vllm serve {{model_path}} \
    --served-model-name {{served_name}} \
    --uds "$work/vllm.sock" \
    --tensor-parallel-size {{gpus}} \
    {{extra_arguments}} &
server=$!
{{container_runtime}} {{container}} python3 "$work/key_proxy.py" "$work/vllm.sock" "$port" &
gatekeeper=$!

# Loading the model takes a few minutes. The gatekeeper opens its port once vLLM is
# ready, so an open port means a server that answers: then write down where it is.
until (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; do
    if ! kill -0 "$server" 2>/dev/null || ! kill -0 "$gatekeeper" 2>/dev/null; then
        echo "The server stopped before it was ready: see the messages above." >&2
        exit 1
    fi
    if [ -e "$stop_file" ]; then echo "The organizers stopped this job." >&2; exit 0; fi
    sleep 2
done
printf '{"job": "%s", "kind": "%s", "model": "%s", "node": "%s", "port": %s, "key": "%s"}\n' \
    "$SLURM_JOB_ID" "{{kind}}" "{{request_name}}" "$(hostname -s)" "$port" "$GAGNVIST_KEY" \
    >"$address"
echo "Ready: {{request_name}} on $(hostname -s), port $port"

while kill -0 "$server" 2>/dev/null && kill -0 "$gatekeeper" 2>/dev/null; do
    if [ -e "$stop_file" ]; then echo "The organizers stopped this job." >&2; exit 0; fi
    sleep 2
done
echo "The server stopped: see the messages above." >&2
exit 1
