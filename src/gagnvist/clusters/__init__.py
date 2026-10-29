"""The supercomputers the starter kit can use: LUMI and JURECA.

Each is described by a :class:`~gagnvist.clusters.profile.Cluster`, which holds every
fact that differs between them; the code that uses the facts is in :mod:`gagnvist.lumi`.
"""

from __future__ import annotations

from gagnvist.clusters.jureca import JURECA
from gagnvist.clusters.lumi import LUMI
from gagnvist.clusters.profile import Cluster

CLUSTERS: dict[str, Cluster] = {LUMI.name: LUMI, JURECA.name: JURECA}
DEFAULT_CLUSTER = LUMI.name


def cluster(name: str) -> Cluster:
    """The supercomputer called ``name``."""
    try:
        return CLUSTERS[name]
    except KeyError:
        raise ValueError(
            f"there is no supercomputer called {name!r}: choose {' or '.join(CLUSTERS)}"
        ) from None


__all__ = ["CLUSTERS", "DEFAULT_CLUSTER", "JURECA", "LUMI", "Cluster", "cluster"]
