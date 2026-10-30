"""What differs between the supercomputers the starter kit can use.

The code in :mod:`gagnvist.lumi` (ssh, tunnels, jobs, the job scripts) was written for
LUMI and runs unchanged for JURECA: a login over ssh, Slurm jobs, vLLM in a container.
Everything that is *not* the same is a fact about one supercomputer, kept in a
:class:`Cluster` and nowhere else: its login host, where your files go, how a job asks
for GPUs and finds the container runtime, what a job costs, and the limits the starter
kit sets. :mod:`gagnvist.clusters.lumi` and :mod:`gagnvist.clusters.jureca` hold the
two profiles; :func:`gagnvist.clusters.cluster` finds one by name.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Cluster:
    """One supercomputer: the facts about it that the code needs."""

    name: str  # the command, `gagnvist <name> ...`, and the value of --cluster
    label: str  # how messages call it
    docs: str  # the guide to it, in the starter kit
    # The names of your personal settings for it in .env (used in messages).
    username_setting: str
    ssh_key_setting: str
    local_port_setting: str
    # Ports on your computer for tunnels to servers of your own, by kind (the shared
    # models use the cluster's local_port), so that every tunnel can be open at once.
    own_server_ports: dict[str, int]
    # The project and its folders. {project} and {username} are filled in.
    project_pattern: str  # what a project name looks like
    project_root: str  # the project's folder, which every member can see
    user_folder: str  # where your gagnvist folder goes
    path_pattern: str  # a full path to a model, for example a teammate's
    # Jobs: the partitions (the first is the default), the most hours a job may ask for
    # on each, and the limits the starter kit sets so that no team can use up the budget.
    partitions: tuple[str, ...]
    partition_hours: dict[str, int]
    partition_help: str  # one line about the choice, for --help
    max_jobs: int  # your jobs, running or waiting, at the same time
    gpu_choices: tuple[int, ...]  # GPUs per job: a model is split evenly between them
    cpus_per_gpu: int  # CPU cores a job asks for, per GPU
    container_group: str  # a group your account needs to run containers ("" if none)
    # A folder of Python libraries that fine-tuning needs and the container lacks
    # (peft), which the organizers fill once and every fine-tuning job puts on its
    # Python path; "" if the container has them. {project} and {gateway_user} are filled in.
    finetune_libraries: str
    # What to do when Slurm refuses the project's GPU partitions to your account: who
    # grants that access, and where ("" if every member has it).
    partition_access_hint: str
    # Logging in. ``multiplex``: open one ssh connection and let every command and
    # tunnel reuse it, for a system that asks for a one-time code at each login.
    multiplex: bool
    # ``ipv4_only``: connect over IPv4 only, for a system that accepts a key only from
    # the networks its from= clause names (IPv4 ranges), which a computer with IPv6
    # would otherwise reach from an IPv6 address the clause does not name.
    ipv4_only: bool
    # How a login node reaches the compute node that Slurm calls ``node``: "{node}"
    # itself, or another name of the same node, for example on a faster network.
    node_address: str
    key_hint: str  # what to check when the key is refused
    host_key_hint: str  # where the host key's fingerprints are published
    # Pieces of the job scripts (job_templates/*.sbatch).
    modules: str  # shell lines that make the container runtime available in a job
    login_modules: str  # the same on a login node, quietly
    container_runtime: str  # the command that runs a program in the container, on a GPU node
    login_container_runtime: str  # the same on a login node (no GPU)
    gpu_environment: str  # exported variables the GPUs' libraries need ("" if none)
    gpu_request: str  # the #SBATCH lines that ask for {gpus} GPUs
    # Cost: either per GPU (LUMI) or per node (JURECA).
    cost_per_gpu_hour: float  # GPU-hours billed per GPU per hour, 0 if billed per node
    cost_per_node_hour: int  # core-hours billed per node per hour, 0 if billed per GPU

    def folder(self, project: str, username: str) -> str:
        """Where your gagnvist folder goes on this supercomputer."""
        return self.user_folder.format(project=project, username=username)

    def job_pieces(self, gpus: int) -> dict[str, str]:
        """The placeholders of a job script that differ between supercomputers."""
        return {
            "modules": self.modules,
            "container_runtime": self.container_runtime,
            "gpu_environment": self.gpu_environment,
            "gpu_request": self.gpu_request.format(gpus=gpus),
        }

    def resource_problem(self, gpus: int, hours: int, partition: str) -> str | None:
        """Why a job cannot be asked for, in words; None if it can."""
        if partition not in self.partitions:
            return f"use the partition {' or '.join(self.partitions)}, not {partition!r}"
        if gpus not in self.gpu_choices:
            choices = ", ".join(str(n) for n in self.gpu_choices)
            return f"ask for {choices} GPU chips (a model is split evenly), not {gpus}"
        longest = self.partition_hours[partition]
        if not 1 <= hours <= longest:
            return f"ask for 1 to {longest} hours on {partition}, not {hours}"
        return None

    def cost(self, gpus: int, hours: int) -> str:
        """What a job of ``gpus`` GPUs for ``hours`` costs at most, in words."""
        if self.cost_per_node_hour:
            core_hours = self.cost_per_node_hour * hours
            return (
                f"In its {hours} h it uses at most {core_hours:,} core-hours of the hackathon's "
                f"budget: a whole node, {self.cost_per_node_hour} core-hours per hour, "
                "however many GPUs it asks for."
            )
        gpu_hours = self.cost_per_gpu_hour * gpus * hours
        return (
            f"In its {hours} h it uses at most {gpu_hours:g} GPU-hours of the hackathon's budget."
        )
