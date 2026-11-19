"""Albert Health x DHA Health Data Sandbox — analiz paketi (S-2025-Y4B7N9).

Offline çalışacak şekilde tasarlandı: yalnızca numpy, pandas, matplotlib.
İlk import repo kökündeki git dışı `.env`'i ortama yükler (envfile.py; ayarlı değişkeni ezmez).
"""
from . import envfile as _envfile

_envfile.load()

__version__ = "0.1.0"
