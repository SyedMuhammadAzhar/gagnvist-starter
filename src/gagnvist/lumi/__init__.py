"""Working with the supercomputer from your computer: tunnels to the shared models, and
jobs of your own. (The package is named after LUMI, the supercomputer it was written
for; this edition of the starter kit uses it for JURECA, see :mod:`gagnvist.clusters`.)

- :mod:`~gagnvist.lumi.connection`: running commands on the supercomputer and opening
  tunnels, with your own SSH key;
- :mod:`~gagnvist.lumi.jobs`: downloading models, starting and stopping model servers
  and fine-tuning jobs, all under your own account;
- :mod:`~gagnvist.lumi.tunnel`: keeping a tunnel open until you press Ctrl+C;
- ``job_templates/``: the Slurm job scripts that run there.
"""
