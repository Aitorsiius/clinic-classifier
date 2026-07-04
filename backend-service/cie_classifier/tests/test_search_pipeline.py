"""Tests del pipeline semántico de ``MedicalSearchEngine.search`` y auxiliares.

Se evita el ``__init__`` real (que conecta con servicios externos) creando la
instancia con ``object.__new__`` e inyectando un cliente Qdrant falso. Las
llamadas HTTP a embeddings y reranker se simulan parcheando ``main.requests``.
"""
import main
from main import (
    MedicalSearchEngine,
    axis_match_adjustment,
    complication_status,
    detect_anatomical_sites,
    detect_laterality,
    is_primary_default_variant,
    is_unspecified_variant,
    lexical_overlap,
    neutralize_wildcard_terms,
    print_traceability,
    promote_conservative_default,
)


def _engine():
    return object.__new__(MedicalSearchEngine)


class _FakeHit:
    def __init__(self, code, score, search_text="passage: texto tecnico", title=None):
        self.payload = {
            "id": code,
            "title": title if title is not None else code,
            "search_text": search_text,
            "metadata": {"hierarchy": []},
        }
        self.score = score


class _FakePoints:
    def __init__(self, hits):
        self.points = hits


class _FakeClient:
    def __init__(self, hits):
        self._hits = hits
        self.last_query = None

    def query_points(self, collection_name=None, query=None, limit=None, **kwargs):
        self.last_query = query
        return _FakePoints(self._hits)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def _patch_requests(monkeypatch, vector, rerank_scores, captured=None):
    def fake_post(url, json=None, timeout=None, **kwargs):
        if url == main.EMBEDDING_URL:
            if captured is not None:
                captured["embed_input"] = json["inputs"]
            return _FakeResponse([vector])
        if captured is not None:
            captured["rerank_pairs"] = json["inputs"]
        return _FakeResponse(rerank_scores)

    monkeypatch.setattr(main.requests, "post", fake_post)


# ----------------------------------------------------------------------------
# neutralize_wildcard_terms — saneado de comodines CIE-10
# ----------------------------------------------------------------------------
def test_neutralize_removes_no_especificada():
    assert neutralize_wildcard_terms("Insuficiencia cardiaca, no especificada") == "Insuficiencia cardiaca"


def test_neutralize_removes_variants_and_abbreviations():
    assert neutralize_wildcard_terms("Miocardiopatía no especificada") == "Miocardiopatía"
    assert neutralize_wildcard_terms("Gastritis SAI") == "Gastritis"
    assert neutralize_wildcard_terms("Tumor, sin especificar") == "Tumor"
    assert neutralize_wildcard_terms("Lesión no clasificada en otra parte") == "Lesión"


def test_neutralize_preserves_sin_complicaciones():
    # "sin complicaciones" es un eje discriminante real y NO debe eliminarse.
    texto = "Diabetes mellitus sin complicaciones"
    assert neutralize_wildcard_terms(texto) == texto


def test_neutralize_handles_empty_and_clinical_text():
    assert neutralize_wildcard_terms("") == ""
    assert neutralize_wildcard_terms("fiebre y tos") == "fiebre y tos"


# ----------------------------------------------------------------------------
# Desempate por ejes: lateralidad y localización
# ----------------------------------------------------------------------------
def test_detect_laterality_variants():
    assert detect_laterality("mano derecha") == {"right"}
    assert detect_laterality("rodilla izquierda") == {"left"}
    assert detect_laterality("ambas manos") == {"bilateral"}
    assert detect_laterality("afectación bilateral") == {"bilateral"}
    # Mencionar los dos lados equivale a bilateral.
    assert detect_laterality("mano derecha e izquierda") == {"bilateral"}
    assert detect_laterality("artritis reumatoide") == set()


def test_detect_anatomical_sites():
    assert detect_anatomical_sites("dolor en ambas manos") == {"mano"}
    assert "hombro" in detect_anatomical_sites("artritis de hombro y codo")
    assert "codo" in detect_anatomical_sites("artritis de hombro y codo")
    assert detect_anatomical_sites("malestar general") == set()


def test_axis_adjustment_rewards_match():
    adj = axis_match_adjustment("ambas manos", "artritis reumatoide de ambas manos")
    # Coincide lateralidad y localización -> doble bonificación.
    assert adj == main._AXIS_MATCH_BONUS * 2


def test_axis_adjustment_penalizes_contradiction():
    # Consulta bilateral frente a candidato de un solo lado: contradicción.
    adj = axis_match_adjustment("ambas manos", "artritis reumatoide de mano izquierda")
    # Lateralidad contradicha (-penalty) pero la localización (mano) coincide (+bonus).
    assert adj == main._AXIS_MATCH_BONUS - main._AXIS_CONTRADICTION_PENALTY


def test_axis_adjustment_neutral_when_axis_absent():
    # El candidato no aporta lateralidad ni localización -> sin ajuste.
    assert axis_match_adjustment("ambas manos", "artritis reumatoide no especificada") == 0.0


# ----------------------------------------------------------------------------
# Defecto conservador ante empate técnico
# ----------------------------------------------------------------------------
def test_is_unspecified_variant_by_title_and_code():
    assert is_unspecified_variant({"id": "M05.049", "title": "Síndrome de Felty, mano no especificada"})
    assert is_unspecified_variant({"id": "I50.9", "title": "Insuficiencia cardiaca"})  # código .9
    assert not is_unspecified_variant({"id": "M05.042", "title": "Síndrome de Felty, mano izquierda"})
    # "Otros tipos" NO es la variante residual aunque acabe en dígito alto.
    assert not is_unspecified_variant({"id": "J45.998", "title": "Otros tipos de asma"})


def test_lexical_overlap_matches_same_disease_not_intruder():
    # Misma enfermedad (tiroides) -> solapamiento alto; intruso (paratiroides) -> 0.
    assert lexical_overlap("Hipotiroidismo sin complicaciones", "Hipotiroidismo, no especificado") > 0.5
    assert lexical_overlap("Hipotiroidismo sin complicaciones", "Hiperparatiroidismo, no especificado") == 0.0
    # Las palabras de cabecera ("síndrome") y los comodines no cuentan como señal.
    assert lexical_overlap("Síndrome de Felty", "Síndrome de Sjögren no especificado") == 0.0


def test_lexical_overlap_is_directed_and_rewards_modifier_coverage():
    # Coeficiente dirigido (|q∩d|/|q|): NO penaliza al título por ser más largo.
    q = "Anemia ferropénica"
    # El específico cubre el 100% de los modificadores de la consulta.
    assert lexical_overlap(q, "Anemia ferropénica, no especificada") == 1.0
    # El genérico absoluto solo cubre "anemia" -> 50%.
    assert lexical_overlap(q, "Anemia, no especificada") == 0.5


def _r(code, score, title=None):
    return {"score": score, "payload": {"id": code, "title": title or code}}


def test_promotes_generic_matching_enriched_query():
    # Empate estrecho (0.02); el genérico .9 coincide léxicamente con la query -> sube.
    results = [
        _r("E03.1", 0.88, "Hipotiroidismo congénito sin bocio difuso"),
        _r("E03.9", 0.86, "Hipotiroidismo, no especificado"),
    ]
    out = promote_conservative_default(results, "Hipotiroidismo sin complicaciones")
    assert out[0]["payload"]["id"] == "E03.9"
    assert out[0]["score"] == 0.88  # confianza igualada al top del empate


def test_no_promotion_when_generic_is_lexical_intruder():
    # El genérico en empate es de OTRA patología (paratiroides) que el vectorial
    # arrastró por error: la validación léxica lo descarta, no se promueve.
    results = [
        _r("E03.8", 0.88, "Otro hipotiroidismo especificado"),
        _r("E21.3", 0.86, "Hiperparatiroidismo, no especificado"),
    ]
    out = promote_conservative_default(results, "Hipotiroidismo sin complicaciones")
    assert out[0]["payload"]["id"] == "E03.8"


def test_no_promotion_when_margin_too_wide():
    results = [
        _r("E03.1", 0.90, "Hipotiroidismo congénito sin bocio difuso"),
        _r("E03.9", 0.80, "Hipotiroidismo, no especificado"),
    ]
    out = promote_conservative_default(results, "Hipotiroidismo sin complicaciones")
    assert out[0]["payload"]["id"] == "E03.1"


def test_no_op_when_top_already_unspecified():
    results = [
        _r("E03.9", 0.88, "Hipotiroidismo, no especificado"),
        _r("E03.1", 0.87, "Hipotiroidismo congénito sin bocio difuso"),
    ]
    out = promote_conservative_default(results, "Hipotiroidismo sin complicaciones")
    assert out[0]["payload"]["id"] == "E03.9"


def test_promotes_specific_generic_over_absolute_by_modifiers():
    # "Secuestro de jerarquía": empate de dos genéricos; con el modificador
    # "ferropénica" debe ganar D50.9 sobre el genérico absoluto D64.9.
    results = [
        _r("D50.0", 0.88, "Anemia ferropénica secundaria a pérdida de sangre (crónica)"),
        _r("D64.9", 0.86, "Anemia, no especificada"),
        _r("D50.9", 0.85, "Anemia ferropénica, no especificada"),
    ]
    out = promote_conservative_default(results, "Anemia ferropénica")
    assert out[0]["payload"]["id"] == "D50.9"
    assert out[0]["score"] == 0.88


def test_rescues_specific_generic_even_if_absolute_is_top():
    # El genérico absoluto D64.9 ya está en el Top 1 (el caso reportado): debe
    # rescatarse el genérico específico D50.9 empatado por debajo.
    results = [
        _r("D64.9", 0.88, "Anemia, no especificada"),
        _r("D50.9", 0.86, "Anemia ferropénica, no especificada"),
    ]
    out = promote_conservative_default(results, "Anemia ferropénica")
    assert out[0]["payload"]["id"] == "D50.9"


def test_absolute_generic_kept_on_top_when_no_modifier():
    # Sin modificador en la consulta, el genérico absoluto (más general) se mantiene.
    results = [
        _r("D64.9", 0.88, "Anemia, no especificada"),
        _r("D50.9", 0.86, "Anemia ferropénica, no especificada"),
    ]
    out = promote_conservative_default(results, "Anemia")
    assert out[0]["payload"]["id"] == "D64.9"


def test_is_primary_default_variant():
    assert is_primary_default_variant({"id": "I10", "title": "Hipertensión esencial (primaria)"})
    assert is_primary_default_variant({"id": "I27.0", "title": "Hipertensión pulmonar primaria"})
    assert not is_primary_default_variant({"id": "I15.1", "title": "Hipertensión secundaria a otros trastornos renales"})
    # "Otros/otras" no es la variante por defecto.
    assert not is_primary_default_variant({"id": "I15.8", "title": "Otra hipertensión secundaria"})


def test_promotes_primary_when_no_unspecified_in_block():
    # Empate sin variante "no especificada": para etiología no declarada se fuerza la
    # variante "esencial/primaria" (I10) frente a la "secundaria".
    results = [
        _r("I15.1", 0.88, "Hipertensión secundaria a otros trastornos renales"),
        _r("I10", 0.86, "Hipertensión esencial (primaria)"),
    ]
    out = promote_conservative_default(results, "Hipertensión arterial")
    assert out[0]["payload"]["id"] == "I10"
    assert out[0]["score"] == 0.88


def test_unspecified_takes_precedence_over_primary():
    # Si en el bloque SÍ hay un "no especificada", manda esa (la primaria es fallback).
    results = [
        _r("I10", 0.88, "Hipertensión esencial (primaria)"),
        _r("I15.9", 0.86, "Hipertensión secundaria, no especificada"),
    ]
    out = promote_conservative_default(results, "Hipertensión arterial")
    assert out[0]["payload"]["id"] == "I15.9"


def test_complication_status():
    # "con X" no pedida -> -1; "sin X" -> 0; "con X" pedida -> +1.
    assert complication_status("Cistitis, no especificada, con hematuria", "cistitis aguda") == -1
    assert complication_status("Cistitis, no especificada, sin hematuria", "cistitis aguda") == 0
    assert complication_status("Cistitis, no especificada, con hematuria", "cistitis con hematuria") == 1


def test_promote_defaults_to_sin_complication():
    # Empate de variantes genéricas con/sin hematuria; sin pedirla, gana "sin".
    results = [
        _r("N30.91", 0.88, "Cistitis, no especificada, con hematuria"),
        _r("N30.90", 0.86, "Cistitis, no especificada, sin hematuria"),
    ]
    out = promote_conservative_default(results, "Cistitis aguda")
    assert out[0]["payload"]["id"] == "N30.90"


def test_promote_picks_con_complication_when_requested():
    # Si la consulta pide la complicación, sí se promueve la variante "con".
    results = [
        _r("N30.90", 0.88, "Cistitis, no especificada, sin hematuria"),
        _r("N30.91", 0.86, "Cistitis, no especificada, con hematuria"),
    ]
    out = promote_conservative_default(results, "Cistitis con hematuria")
    assert out[0]["payload"]["id"] == "N30.91"


# ----------------------------------------------------------------------------
# _get_vector_from_docker
# ----------------------------------------------------------------------------
def test_get_vector_from_docker(monkeypatch):
    engine = _engine()
    resp = _FakeResponse([[0.1, 0.2, 0.3]])
    monkeypatch.setattr(main.requests, "post", lambda *a, **k: resp)
    assert engine._get_vector_from_docker("query: x") == [0.1, 0.2, 0.3]


# ----------------------------------------------------------------------------
# search() — ruta semántica
# ----------------------------------------------------------------------------
def test_search_semantic_pipeline(monkeypatch):
    engine = _engine()
    engine.client = _FakeClient([_FakeHit("A00.0", 0.8), _FakeHit("B10", 0.6)])
    _patch_requests(monkeypatch, vector=[0.1, 0.2], rerank_scores=[3.0, -2.0])

    results = engine.search("dolor de cabeza intenso", top_k=2)
    assert len(results) == 2
    # El primer hit tiene mayor logit -> mayor score híbrido -> va primero.
    assert results[0]["payload"]["id"] == "A00.0"
    assert results[0]["score"] > results[1]["score"]
    assert all(0.0 <= r["score"] <= 1.0 for r in results)


def test_search_uses_enriched_query(monkeypatch):
    engine = _engine()
    client = _FakeClient([_FakeHit("A00.0", 0.8)])
    engine.client = client
    _patch_requests(monkeypatch, vector=[0.1, 0.2], rerank_scores=[1.0])

    engine.search("tos", top_k=1, enriched_query="infeccion respiratoria aguda")
    # El texto enriquecido se prefija con 'query: ' al pedir el embedding, pero
    # el vector es el mismo; comprobamos que la búsqueda se ejecutó.
    assert client.last_query == [0.1, 0.2]


def test_search_strips_wildcards_from_query_and_documents(monkeypatch):
    # El catálogo trae títulos residuales acabados en "no especificada" y la
    # consulta enriquecida también; ambos lados deben llegar saneados a la
    # similitud (embedding) y al re-ranking (pares del cross-encoder).
    engine = _engine()
    engine.client = _FakeClient(
        [_FakeHit("I50.9", 0.8, search_text="passage: Insuficiencia cardiaca, no especificada")]
    )
    captured = {}
    _patch_requests(monkeypatch, vector=[0.1, 0.2], rerank_scores=[1.0], captured=captured)

    engine.search(
        "fiebre y diarrea",
        top_k=1,
        enriched_query="Síndrome constitucional, no especificado",
    )

    # El texto del embedding no contiene el comodín pero sí el contenido clínico.
    assert "no especificado" not in captured["embed_input"].lower()
    assert "Síndrome constitucional" in captured["embed_input"]
    # Los pares del reranker (consulta y documento) llegan también sin comodín.
    query_side, doc_side = captured["rerank_pairs"][0]
    assert "no especificado" not in query_side.lower()
    assert "no especificada" not in doc_side.lower()
    assert "Insuficiencia cardiaca" in doc_side


def test_search_axis_rerank_breaks_laterality_tie(monkeypatch):
    # El cross-encoder empata (mismo logit) un código bilateral y uno de un solo
    # lado; el desempate por ejes debe colocar el bilateral correcto por delante.
    engine = _engine()
    engine.client = _FakeClient(
        [
            _FakeHit("M05_izq", 0.8, search_text="passage: Artritis reumatoide de mano izquierda"),
            _FakeHit("M05_bil", 0.8, search_text="passage: Artritis reumatoide de ambas manos"),
        ]
    )
    # Mismo score de reranker para ambos -> empate técnico antes del desempate.
    _patch_requests(monkeypatch, vector=[0.1, 0.2], rerank_scores=[2.0, 2.0])

    results = engine.search("artritis reumatoide en ambas manos", top_k=2)
    assert results[0]["payload"]["id"] == "M05_bil"
    assert results[0]["score"] > results[1]["score"]


def test_search_promotes_conservative_default_on_tie(monkeypatch):
    # Sin datos de lateralidad en la consulta, el reranker empata la variante de un
    # lado y la residual; la capa final debe entregar la "no especificada" como Top 1.
    engine = _engine()
    engine.client = _FakeClient(
        [
            _FakeHit(
                "M05.042", 0.8,
                search_text="passage: Síndrome de Felty, mano izquierda",
                title="Síndrome de Felty, mano izquierda",
            ),
            _FakeHit(
                "M05.049", 0.8,
                search_text="passage: Síndrome de Felty, mano no especificada",
                title="Síndrome de Felty, mano no especificada",
            ),
        ]
    )
    _patch_requests(monkeypatch, vector=[0.1, 0.2], rerank_scores=[2.0, 2.0])

    results = engine.search("sindrome de felty", top_k=2)
    assert results[0]["payload"]["id"] == "M05.049"


def test_search_reranker_failure_falls_back_to_vector(monkeypatch):
    engine = _engine()
    engine.client = _FakeClient([_FakeHit("A00.0", 0.7)])

    def fake_post(url, json=None, timeout=None, **kwargs):
        if url == main.EMBEDDING_URL:
            return _FakeResponse([[0.1, 0.2]])
        raise RuntimeError("reranker caido")

    monkeypatch.setattr(main.requests, "post", fake_post)
    results = engine.search("dolor", top_k=1)
    # Con el reranker caído, el score es el del vector (fallback).
    assert results[0]["score"] == 0.7


def test_search_no_hits_returns_empty(monkeypatch):
    engine = _engine()
    engine.client = _FakeClient([])
    _patch_requests(monkeypatch, vector=[0.1, 0.2], rerank_scores=[])
    assert engine.search("algo raro", top_k=3) == []


def test_search_code_shortcut(monkeypatch):
    engine = _engine()

    captured = {}

    def fake_exact(code, top_k=5):
        captured["code"] = code
        return [{"score": 1.0, "payload": {"id": code}}]

    engine.search_by_code_exact = fake_exact
    results = engine.search("A00.0", top_k=5)
    assert results[0]["payload"]["id"] == "A00.0"
    assert captured["code"] == "A00.0"


# ----------------------------------------------------------------------------
# print_traceability (no debe lanzar)
# ----------------------------------------------------------------------------
def test_print_traceability_empty(capsys):
    print_traceability([])
    assert "No se encontraron" in capsys.readouterr().out


def test_print_traceability_with_results(capsys):
    results = [
        {
            "score": 0.9,
            "payload": {
                "id": "A00.0",
                "title": "Colera",
                "metadata": {"hierarchy": [{"code": "A00-A09", "title": "Infecciosas"}]},
            },
        }
    ]
    print_traceability(results)
    out = capsys.readouterr().out
    assert "A00.0" in out
    assert "Colera" in out
