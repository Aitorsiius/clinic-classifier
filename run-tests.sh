#!/usr/bin/env bash
# ============================================================================
# Ejecuta los tests de cada microservicio Python por separado y genera un
# informe de cobertura por servicio (coverage-<nombre>.xml en la raíz) que
# SonarCloud recoge mediante el patrón coverage-*.xml.
#
# Se ejecuta cada servicio en su propio proceso de pytest porque todos tienen
# un módulo "main": compartir un único proceso provocaría colisiones de import.
#
# Uso:
#   ./run-tests.sh          # activa .venv si existe y lanza todo
# ============================================================================
set -u

# Activar el entorno virtual si existe y no está ya activo.
if [[ -z "${VIRTUAL_ENV:-}" && -f ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# Pares "ruta_del_servicio:nombre_corto" (el nombre va en coverage-<nombre>.xml).
services=(
  "audit-service:audit"
  "auth-service:auth"
  "api-gateway:gateway"
  "backend-service/cie_classifier:backend"
  "history-service:history"
  "log-service:log"
  "llm-query-processor-service:llm"
)

status=0
for entry in "${services[@]}"; do
  path="${entry%%:*}"
  name="${entry##*:}"
  echo ""
  echo "=============================================================="
  echo " Tests: ${path}"
  echo "=============================================================="
  python -m pytest "${path}/tests" \
    --cov="${path}" \
    --cov-config=.coveragerc \
    --cov-report="xml:coverage-${name}.xml" \
    --cov-report=term-missing || status=1
done

echo ""
if [[ "${status}" -eq 0 ]]; then
  echo "[OK] Todos los tests pasaron. Informes: coverage-*.xml"
else
  echo "[FALLO] Algun test fallo (ver salida anterior)."
fi
exit "${status}"
