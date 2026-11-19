"""Albert Health x DHA Health Data Sandbox — analysis package (S-2025-Y4B7N9).

Designed to run offline: numpy, pandas, matplotlib only.
The first import loads the untracked `.env` at the repo root into the environment (envfile.py; never overwrites a set variable).
"""
from . import envfile as _envfile

_envfile.load()

__version__ = "0.1.0"
