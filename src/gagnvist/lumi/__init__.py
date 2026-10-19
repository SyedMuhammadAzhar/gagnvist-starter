"""Working with LUMI from your computer: tunnels to the shared models, and jobs of your own.

- :mod:`~gagnvist.lumi.connection`: running commands on LUMI and opening tunnels, with
  your own SSH key;
- :mod:`~gagnvist.lumi.jobs`: downloading models, starting and stopping model servers
  and fine-tuning jobs, all under your own account;
- :mod:`~gagnvist.lumi.tunnel`: keeping a tunnel open until you press Ctrl+C;
- ``job_templates/``: the Slurm job scripts that run on LUMI.
"""
