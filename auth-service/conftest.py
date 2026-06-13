"""Configuración de pytest para auth-service.

- Añade el directorio del servicio al ``sys.path``.
- Define las variables de entorno obligatorias (``JWT_SECRET``).
- Sustituye ``MongoClient`` para que la conexión falle de inmediato (sin esperar
  el timeout real de 5 s) durante la importación de ``main``; ``init_mongodb``
  captura el error y continúa sin base de datos.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("JWT_SECRET", "test-secret-key-not-for-production")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_EXPIRATION_HOURS", "24")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost")

import pymongo
from pymongo.errors import ServerSelectionTimeoutError


def _fail_fast(*args, **kwargs):
    raise ServerSelectionTimeoutError("MongoDB no disponible en tests")


pymongo.MongoClient = _fail_fast
