"""Configuración de pytest para audit-service.

Añade el directorio del servicio al ``sys.path`` para poder importar ``audit``
y ``main`` directamente, e inyecta valores de entorno inofensivos.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost")
