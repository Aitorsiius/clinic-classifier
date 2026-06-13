"""Configuración de pytest para history-service.

Añade el directorio del servicio al ``sys.path``, define ``JWT_SECRET`` y hace
que la conexión a MongoDB falle rápido durante la importación de ``main``.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("JWT_SECRET", "test-secret-key-not-for-production")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost")

import pymongo
from pymongo.errors import ServerSelectionTimeoutError


def _fail_fast(*args, **kwargs):
    raise ServerSelectionTimeoutError("MongoDB no disponible en tests")


pymongo.MongoClient = _fail_fast
