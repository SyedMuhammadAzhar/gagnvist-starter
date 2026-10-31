"""JURECA, the supercomputer of the Jülich Supercomputing Centre, Germany
(https://apps.fz-juelich.de/jsc/hps/jureca/).

NVIDIA A100 GPUs, four per node. A job always gets a whole node, however many of its
GPUs it asks for, and is billed for the node's 128 cores: 128 core-hours per hour. The
container is run with apptainer, which is on the path without any module; running
containers needs the account to be in the ``container`` group (asked for in JuDoor).
Accounts and SSH keys come from JuDoor; a key is only accepted from the networks its
``from=`` clause names. The compute nodes have no internet, so models are downloaded
on a login node.

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
tunnels through the shared ssh connection (see ``lumi/connection.py``).

Checked live on the night of 2026-10-30: a login node reaches a compute node only by
its InfiniBand name, ``jrc0193i`` (Slurm's NodeAddr; port 22 open), not by the name
squeue prints, ``jrc0193`` (port 22 refused, other ports dropped): hence
``node_address``. ``jureca.fz-juelich.de`` has IPv6 addresses, and JSC's access page
says a client that prefers IPv6 needs a from= clause with its IPv6 address: hence
``ipv4_only``. The nodes run Rocky Linux 9.8; the login node's NVIDIA driver is
610.57.04, enough for the CUDA 13.0 of vLLM's image v0.32.0 (9.2 GB to pull); the
A100s have 40 GB each; the QoS ``normal`` allows 24 h per job, and ``dc-gpu-devel``
2 running jobs. Apptainer's site configuration binds all of ``/p`` (``bind path = /p``),
so the ``--bind`` below is belt and braces; ``/p/project`` and ``/p/fastdata`` do not
exist on JURECA (``/p/project1``, ``/p/scratch`` and ``/p/data1`` do). vLLM's image
lacks ``peft``, which fine-tuning imports (checked against the image's Dockerfile and
requirements, v0.32.0; everything else peft needs, accelerate included, is in the
image): hence ``finetune_libraries``.

Checked live on 2026-10-31, 02:17 UTC: Slurm 25.05 (``srun`` does not take
``--cpus-per-task`` over from the job, as JSC's own job script examples note: the job
scripts export ``SRUN_CPUS_PER_TASK``); QoS ``normal`` 24 h, 64 running and 512
submitted jobs per user, ``dc-gpu-devel`` 2 h, 2 running and 4 submitted; the login
shell's umask is 0022; a home folder (``/p/home/jusers/<user>/jureca``) has 20 GB and
80,000 files, which is why models, caches and the organizers' libraries live under
``/p/project1``; the compute nodes' driver supports CUDA 13 (JSC's known-issues page:
driver update of 2025-08-28). Still unverified: vLLM itself on the A100 nodes, and the
gateway job end to end (the organizers' runbook has the smoke tests).
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
    path_pattern=r"/p/(?:project1|scratch|data1)/[a-z][a-z0-9_-]{1,31}/[A-Za-z0-9_./-]+",
    partitions=("dc-gpu", "dc-gpu-devel"),
    partition_hours={"dc-gpu": 6, "dc-gpu-devel": 2},
    partition_help=(
        "dc-gpu-devel, for quick tests only, often starts sooner but allows at most 2 hours"
    ),
    max_jobs=2,  # a chat model and an embedding model, each on a whole node
    gpu_choices=(1, 2, 4),
    cpus_per_gpu=8,
    container_group="container",
    finetune_libraries="/p/project1/{project}/{gateway_user}/gagnvist/pylibs",  # peft: see below
    partition_access_hint=(
        "On JURECA the project manager has to give your membership the project's GPU "
        "budget (JURECA-DC_GPU) in JuDoor; ask the organizers."
    ),
    multiplex=True,  # JURECA may ask for a one-time code at every login
    ipv4_only=True,  # a from= clause names IPv4 ranges; jureca.fz-juelich.de has IPv6 too
    node_address="{node}i",  # the node's InfiniBand name (jrc0193i): see the docstring
    key_hint=(
        "A key added in JuDoor takes up to 15 minutes to work, and its from= clause must "
        "name the network you are on now (ask a search engine 'what is my IP')."
    ),
    host_key_hint="JURECA's host key (its fingerprints are on JuDoor's SSH keys page)",
    modules="module purge",
    login_modules="module purge >/dev/null 2>&1",
    # --bind: the models and adapters are under /p/project1. JURECA's apptainer.conf binds
    # all of /p already, and mounts /tmp and your home folder (checked 2026-10-31), so this
    # only keeps the jobs working if that site setting changes; /p/data1 paths rely on it.
    container_runtime="apptainer exec --nv --bind /p/project1,/p/scratch",
    login_container_runtime="apptainer exec --bind /p/project1,/p/scratch",
    gpu_environment="",
    gpu_request="#SBATCH --gres=gpu:{gpus}",
    cost_per_gpu_hour=0,
    cost_per_node_hour=128,
)
