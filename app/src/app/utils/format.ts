/**
 * Utilidades de formato compartidas por la UI.
 */

/**
 * Da formato legible a una duración expresada en milisegundos.
 *
 * - < 1000 ms  ->  "123 ms"
 * - >= 1000 ms ->  "1.23 s"
 *
 * Devuelve "—" cuando el valor no es válido (null, undefined o NaN), para que
 * la interfaz nunca muestre "NaN" ni "undefined".
 */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms) || ms < 0) {
    return '—';
  }
  if (ms < 1000) {
    return `${Math.round(ms)} ms`;
  }
  return `${(ms / 1000).toFixed(2)} s`;
}

/**
 * Da formato a una duración en milisegundos como segundos con un decimal,
 * pensado para un cronómetro "en vivo" (p. ej. "12.3s").
 */
export function formatElapsedSeconds(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms) || ms < 0) {
    return '0.0s';
  }
  return `${(ms / 1000).toFixed(1)}s`;
}

/**
 * Limpia un texto para mostrarlo sin las comillas que arrastran los campos CSV.
 *
 * Elimina las comillas (dobles o simples) que envuelven el texto y convierte las
 * comillas dobles escapadas ("") en una sola. Pensado para las descripciones de
 * diagnóstico, que en los CSV vienen entrecomilladas; así la UI nunca las muestra.
 */
export function cleanDiagnosisText(text: string | null | undefined): string {
  if (!text) {
    return '';
  }
  let cleaned = text.trim();
  // Quitar una pareja de comillas envolventes (dobles o simples).
  if (cleaned.length >= 2) {
    const first = cleaned[0];
    const last = cleaned.at(-1);
    if ((first === '"' && last === '"') || (first === "'" && last === "'")) {
      cleaned = cleaned.slice(1, -1);
    }
  }
  // Comillas dobles escapadas del formato CSV ("") -> comilla simple.
  return cleaned.replaceAll('""', '"').trim();
}
