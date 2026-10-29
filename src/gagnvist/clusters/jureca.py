"""JURECA, the supercomputer of the Jülich Supercomputing Centre, Germany
(https://apps.fz-juelich.de/jsc/hps/jureca/).

NVIDIA A100 GPUs, four per node. A job always gets a whole node, however many of its
GPUs it asks for, and is billed for the node's 128 cores: 128 core-hours per hour. The
container is run with apptainer, which is on the path without any module; running
containers needs the account to be in the ``container`` group (asked for in JuDoor).
Accounts and SSH keys come from JuDoor; a key is only accepted from the networks its
``from=`` clause names. The compute nodes have no internet, so models are downloaded
on a login node, as on LUMI.

A project's GPU time is a budget of its own in JuDoor (JURECA-DC_GPU, next to the CPU
one), and a member can use it only if the project manager gave it to them: without
it, Slurm refuses every job on dc-gpu and dc-gpu-devel ("Invalid account or
account/partition combination specified"). Participants who only use the shared models
need no budget at all.

Checked live on JURECA on 2026-10-29: the project folders (``/p/project1/<project>``
and ``/p/scratch/<project>``), the partitions' limits (dc-gpu 24 h; dc-gpu-devel 2 h,
2 jobs, 4 submitted, per user), whole nodes (OverSubscribe=EXCLUSIVE, 128 billing
units per node-hour), everyone's jobs visible in squeue, apptainer refusing an account
outside the ``container`` group, the GPU budget above, the nodes' names (``jrc0406``;
``hostname`` on a node says ``jrc0406.jureca``, and the login node resolves both), and
tunnels through the shared ssh connection (see ``lumi/connection.py``). Still
unverified: the vLLM image on the A100 driver, and the login node reaching a job's port.
"""

from __future__ import annotations

from gagnvist.clusters.profile import Cluster

JURECA = Cluster(
    name="jureca",
    label="JURECA",
    docs="docs/jureca.md",
    username_setting="GAGNVIST_JURECA_USERNAME",
    ssh_key_setting="GAGNVIST_JURECA_SSH_KEY",
    local_port_setting="GAGNVIST_JURECA_LOCAL_PORT",
    own_server_ports={"chat": 8811, "embeddings": 8812},
    project_pattern=r"[a-z][a-z0-9_-]{1,31}",
    project_root="/p/project1/{project}",
    user_folder="/p/project1/{project}/{username}",
    path_pattern=r"/p/(?:project1?|scratch|fastdata)/[a-z][a-z0-9_-]{1,31}/[A-Za-z0-9_./-]+",
    partitions=("dc-gpu", "dc-gpu-devel"),
    partition_hours={"dc-gpu": 6, "dc-gpu-devel": 2},
    partition_help=(
        "dc-gpu-devel, for quick tests only, often starts sooner but allows at most 2 hours"
    ),
    max_jobs=2,  # a chat model and an embedding model, each on a whole node (as on LUMI)
    gpu_choices=(1, 2, 4),
    cpus_per_gpu=8,
    container_group="container",
    partition_access_hint=(
        "On JURECA the project manager has to give your membership the project's GPU "
        "budget (JURECA-DC_GPU) in JuDoor; ask the organizers."
    ),
    multiplex=True,  # JURECA may ask for a one-time code at every login
    key_hint=(
        "A key added in JuDoor takes up to 15 minutes to work, and its from= clause must "
        "name the network you are on now (JuDoor shows your address)."
    ),
    host_key_hint="JURECA's host key (its fingerprints are on JuDoor's SSH keys page)",
    modules="module purge",
    login_modules="module purge >/dev/null 2>&1",
    # --bind: the models and adapters are under /p/project1, which apptainer does not
    # mount by itself (it mounts your home folder, /tmp and the current folder).
    container_runtime="apptainer exec --nv --bind /p/project1,/p/scratch",
    login_container_runtime="apptainer exec --bind /p/project1,/p/scratch",
    gpu_environment="",
    gpu_request="#SBATCH --gres=gpu:{gpus}",
    cost_per_gpu_hour=0,
    cost_per_node_hour=128,
)
