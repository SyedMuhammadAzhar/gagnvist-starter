"""The supercomputers this edition of the starter kit can use: the ones of the Jülich
Supercomputing Centre (JSC), with JURECA as the default.

Each is described by a :class:`~gagnvist.clusters.profile.Cluster`, which holds every
fact that differs between them; the code that uses the facts is in :mod:`gagnvist.lumi`
(named after LUMI, the supercomputer it was first written for; the LUMI edition of the
starter kit is its ``main`` branch).
"""

from __future__ import annotations

from gagnvist.clusters.jureca import JURECA
from gagnvist.clusters.profile import Cluster

CLUSTERS: dict[str, Cluster] = {JURECA.name: JURECA}
DEFAULT = JURECA  # the supercomputer the commands use unless GAGNVIST_CLUSTER or --cluster say
DEFAULT_CLUSTER = DEFAULT.name


def cluster(name: str) -> Cluster:
    """The supercomputer called ``name``."""
    try:
        return CLUSTERS[name]
    except KeyError:
        raise ValueError(
            f"there is no supercomputer called {name!r}: choose {' or '.join(CLUSTERS)}"
        ) from None


__all__ = ["CLUSTERS", "DEFAULT", "DEFAULT_CLUSTER", "JURECA", "Cluster", "cluster"]
