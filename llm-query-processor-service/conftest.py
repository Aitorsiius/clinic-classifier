"""Configuración de pytest para llm-query-processor-service.

El módulo ``main`` inicializa Vertex AI en tiempo de importación. Para poder
probarlo sin las librerías de Google ni credenciales reales, aquí se:

- Definen ``ID`` y ``LOCATION`` (proyecto/región ficticios).
- Anula ``glob.glob`` para que NO se detecten credenciales JSON reales del repo.
- Inyectan módulos simulados de ``google.*`` y ``vertexai`` en ``sys.modules``
  ANTES de importar ``main`` (el modelo simulado no realiza llamadas de red).
"""
import glob
import os
import sys
import types

sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("ID", "test-project")
os.environ.setdefault("LOCATION", "europe-west1")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost")


def _fake_module(name):
    module = types.ModuleType(name)
    sys.modules[name] = module
    return module


# --- google.* ---
google_mod = _fake_module("google")
google_auth = _fake_module("google.auth")
google_auth.default = lambda *a, **k: (None, None)
google_auth_transport = _fake_module("google.auth.transport")
google_auth_transport_requests = _fake_module("google.auth.transport.requests")
google_auth_transport_requests.Request = object
google_oauth2 = _fake_module("google.oauth2")
google_oauth2_sa = _fake_module("google.oauth2.service_account")


class _Credentials:
    @classmethod
    def from_service_account_file(cls, *args, **kwargs):
        return object()


google_oauth2_sa.Credentials = _Credentials
google_cloud = _fake_module("google.cloud")
google_cloud_aiplatform = _fake_module("google.cloud.aiplatform")
google_cloud_aiplatform.init = lambda *a, **k: None

# Enlazar atributos en los módulos padre.
google_mod.auth = google_auth
google_mod.cloud = google_cloud
google_mod.oauth2 = google_oauth2
google_auth.transport = google_auth_transport
google_auth_transport.requests = google_auth_transport_requests
google_oauth2.service_account = google_oauth2_sa
google_cloud.aiplatform = google_cloud_aiplatform


# --- vertexai.* ---
vertexai_mod = _fake_module("vertexai")
vertexai_mod.init = lambda *a, **k: None
vertex_gen = _fake_module("vertexai.generative_models")


class _FakeModel:
    def __init__(self, *args, **kwargs):
        # No se hace nada, para que no falle la importación de main.
        pass

    def generate_content(self, *args, **kwargs):
        raise RuntimeError("LLM no disponible en tests")


vertex_gen.GenerativeModel = _FakeModel
vertexai_mod.generative_models = vertex_gen


# Importar main AQUÍ, con glob.glob neutralizado SOLO durante la importación
# (para que no se detecten credenciales JSON reales del repo). Se restaura
# después para no romper el descubrimiento de ficheros de coverage.
_original_glob = glob.glob
glob.glob = lambda *args, **kwargs: []
try:
    import main  # noqa: F401  (importado para fijar la configuración de Vertex AI simulada)
finally:
    glob.glob = _original_glob

