"""Allow ``python -m gagnvist`` as well as the ``gagnvist`` command."""

from gagnvist.cli import main

raise SystemExit(main())
