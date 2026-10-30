"""LUMI, the EuroHPC supercomputer in Kajaani, Finland (https://docs.lumi-supercomputer.eu).

AMD MI250X GPUs: a job asks for GPU chips (GCDs) on a node shared with other jobs, and
is billed 0.5 GPU-hours per chip per hour. The container comes from the LUMI AI Factory
and is run with singularity after loading its modules. Accounts come from MyCSC.
"""

from __future__ import annotations

from gagnvist.clusters.profile import Cluster

LUMI = Cluster(
    name="lumi",
    label="LUMI",
    docs="docs/lumi.md",
    username_setting="GAGNVIST_LUMI_USERNAME",
    ssh_key_setting="GAGNVIST_SSH_KEY",
    local_port_setting="GAGNVIST_LOCAL_PORT",
    own_server_ports={"chat": 8801, "embeddings": 8802},
    project_pattern=r"project_\d+",
    project_root="/scratch/{project}",
    user_folder="/scratch/{project}/{username}",
    path_pattern=r"/(?:scratch|project|flash)/project_\d+/[A-Za-z0-9_./-]+",
    partitions=("small-g", "dev-g"),
    partition_hours={"small-g": 12, "dev-g": 3},
    partition_help="dev-g, for quick tests only, often starts sooner but allows at most 3 hours",
    max_jobs=2,
    gpu_choices=(1, 2, 4),
    cpus_per_gpu=7,  # LUMI bills a GPU chip at 0.5 GPU-hours per hour up to 8 cores and 64 GB
    container_group="",
    finetune_libraries="",  # the LUMI AI Factory container ships peft
    partition_access_hint="",  # every member of a LUMI project may use its partitions
    multiplex=False,
    ipv4_only=False,  # lumi.csc.fi has no IPv6 address, and MyCSC keys have no from= clause
    node_address="{node}",  # nid005029 is reached by that name
    key_hint="A key you have just added in MyCSC can take a couple of hours to reach LUMI.",
    host_key_hint="LUMI's host key (see docs/lumi.md)",
    modules="module purge\nmodule load Local-LAIF lumi-aif-singularity-bindings || exit 1",
    login_modules=(
        "module purge >/dev/null 2>&1\n"
        "module load Local-LAIF lumi-aif-singularity-bindings >/dev/null 2>&1 || exit 1"
    ),
    container_runtime="singularity run",
    login_container_runtime="singularity run",
    gpu_environment=(
        'export MIOPEN_CUSTOM_CACHE_DIR="$work/miopen-cache"\n'
        'export MIOPEN_USER_DB_PATH="$work/miopen-config"'
    ),
    gpu_request="#SBATCH --gpus-per-node={gpus}\n#SBATCH --mem-per-gpu=60G",
    cost_per_gpu_hour=0.5,
    cost_per_node_hour=0,
)
