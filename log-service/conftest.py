"""Configuración de pytest para log-service.

Añade el directorio del servicio al ``sys.path`` y hace que la conexión a
MongoDB falle rápido durante la importación de ``main``.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("ALLOWED_ORIGINS", "https://localhost")

import pymongo
from pymongo.errors import ServerSelectionTimeoutError


def _fail_fast(*args, **kwargs):
    raise ServerSelectionTimeoutError("MongoDB no disponible en tests")


pymongo.MongoClient = _fail_fast
