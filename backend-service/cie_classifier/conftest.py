"""Configuración de pytest para backend-service/cie_classifier.

Añade el directorio del servicio al ``sys.path`` para importar ``main`` y
``api``.

Al importar ``api`` se instancia ``MedicalSearchEngine()``, cuyo ``__init__``
intenta conectarse a los servicios de embeddings/reranker (con reintentos y
esperas). Para que la importación sea rápida y determinista en los tests, aquí
se neutraliza la red de ``main`` (``requests`` falla al instante) y se anulan
las esperas (``time.sleep``). El motor queda como ``None`` en ``api`` (su
inicialización está protegida con try/except) y los tests inyectan un motor
falso cuando lo necesitan.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import requests as _requests

import main as _main


def _raise_connection_error(*args, **kwargs):
    raise _requests.exceptions.ConnectionError("Sin red en los tests")


_main.requests.post = _raise_connection_error
_main.requests.get = _raise_connection_error
_main.time.sleep = lambda *args, **kwargs: None

