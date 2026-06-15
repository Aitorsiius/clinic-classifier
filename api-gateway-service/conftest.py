"""Configuración de pytest para api-gateway-service.

Añade el directorio del servicio al ``sys.path`` y define el ``JWT_SECRET``
obligatorio para poder importar ``main`` sin abortar el arranque.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("JWT_SECRET", "test-secret-key-not-for-production")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_EXPIRATION_HOURS", "24")
os.environ.setdefault("ALLOWED_ORIGINS", "https://localhost")
