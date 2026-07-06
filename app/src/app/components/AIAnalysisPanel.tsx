import { ChevronRight, Copy, Check, Stethoscope, Lightbulb } from 'lucide-react';
import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

/**
 * Bloque del asistente inteligente devuelto por la primera fase del pipeline
 * de IA. Es independiente de la lista de resultados de clasificación.
 *
 * - `diagnosis`: interpretación clínica en lenguaje natural de lo que el
 *   usuario ha introducido.
 * - `improvement_tips`: información clínica AUSENTE que, de aportarse, afinaría
 *   la clasificación (lateralidad, temporalidad del contacto, etc.).
 * - `enriched_query`: texto técnico que se envió al buscador (informativo).
 */
export interface AIAssistant {
  diagnosis: string;
  improvement_tips: string[];
  enriched_query?: string;
  is_valid_medical_query?: boolean;
  processing_time_ms?: number;
  original_query?: string;
}

interface AIAnalysisPanelProps {
  data: AIAssistant;
  shouldCollapse?: boolean;
}

export function AIAnalysisPanel({ data, shouldCollapse = false }: Readonly<AIAnalysisPanelProps>) {
  const [isExpanded, setIsExpanded] = useState(true);
  const [copiedText, setCopiedText] = useState<string | null>(null);

  // Cuando shouldCollapse es true, cerrar el panel
  useEffect(() => {
    if (shouldCollapse) {
      setIsExpanded(false);
    }
  }, [shouldCollapse]);

  if (!data) return null;

  const handleCopy = async (text: string, id: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedText(id);
      setTimeout(() => setCopiedText(null), 2000);
    } catch (err) {
      console.error('Error copying to clipboard:', err);
    }
  };

  const contentVariants = {
    collapsed: { height: 0, opacity: 0 },
    expanded: { height: 'auto', opacity: 1, transition: { duration: 0.4, ease: 'easeInOut' } },
  };

  const cardVariants = {
    hidden: { opacity: 0, y: 20 },
    visible: { opacity: 1, y: 0, transition: { duration: 0.4 } },
  };

  // El diagnóstico está vacío o la consulta no es clínicamente interpretable.
  const hasDiagnosis = Boolean(data.diagnosis?.trim());
  const tips = Array.isArray(data.improvement_tips) ? data.improvement_tips : [];
  const isInvalid = data.is_valid_medical_query === false || !hasDiagnosis;

  return (
    <motion.div
      variants={cardVariants}
      layout
      onClick={() => setIsExpanded(!isExpanded)}
      className="bg-white rounded-lg border border-purple-200 shadow-sm hover:shadow-lg transition-all duration-300 p-5 hover:border-purple-300 cursor-pointer mb-8"
    >
      <motion.div layout="position" className="flex items-start justify-between">
        <div className="flex items-start gap-3">
          <div className="flex-1">
            <div className="flex items-center flex-wrap gap-2 mb-2">
              <h3 className="text-lg font-semibold text-purple-900">Asistente Inteligente</h3>
              <span className="text-xs bg-purple-200 text-purple-800 px-2 py-1 rounded font-semibold">Independiente</span>
            </div>
          </div>
        </div>
        <motion.div animate={{ rotate: isExpanded ? 90 : 0 }}>
          <ChevronRight className="w-5 h-5 text-purple-600 flex-shrink-0" />
        </motion.div>
      </motion.div>

      <AnimatePresence>
        {isExpanded && (
          <motion.div
            variants={contentVariants}
            initial="collapsed"
            animate="expanded"
            exit="collapsed"
            className="overflow-hidden"
          >
            <div className="mt-6 pt-4 border-t border-slate-200 space-y-4">
              {/* Nota informativa */}
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 mb-4">
                <p className="text-xs text-blue-800 font-medium">
                  Este asistente interpreta tu texto y sugiere cómo mejorarlo. Es independiente
                  de la clasificación automática: los resultados CIE-10-ES se calculan aparte.
                </p>
              </div>

              {isInvalid ? (
                <div className="bg-amber-50 border border-amber-200 rounded-lg p-6 text-center">
                  <p className="text-sm font-medium text-amber-800 mb-2">⚠️ No se pudo interpretar el diagnóstico</p>
                  <p className="text-xs text-amber-700">
                    El texto proporcionado es demasiado pobre o no contiene información clínica
                    suficiente. Intenta describir el cuadro con más detalle (síntomas, localización,
                    evolución).
                  </p>
                </div>
              ) : (
                <>
                  {/* Diagnóstico interpretado */}
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2 text-sm font-semibold text-slate-600">
                        <Stethoscope className="w-4 h-4 text-purple-600" />
                        Diagnóstico interpretado:
                      </div>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleCopy(data.diagnosis, 'diagnosis');
                        }}
                        className="flex items-center gap-1.5 px-2 py-1 text-xs font-medium rounded bg-purple-100 text-purple-700 hover:bg-purple-200 transition-colors"
                      >
                        {copiedText === 'diagnosis' ? (
                          <>
                            <Check className="w-4 h-4" />
                            Copiado
                          </>
                        ) : (
                          <>
                            <Copy className="w-4 h-4" />
                            Copiar
                          </>
                        )}
                      </button>
                    </div>
                    <div className="bg-white rounded-lg p-3 border border-purple-200">
                      <p className="text-sm text-slate-700 whitespace-pre-wrap break-words">{data.diagnosis}</p>
                    </div>
                  </div>

                  {/* Consejos de mejora */}
                  <div className="space-y-2">
                    <div className="flex items-center gap-2 text-sm font-semibold text-slate-600">
                      <Lightbulb className="w-4 h-4 text-amber-500" />
                      Consejos para mejorar la consulta:
                    </div>
                    {tips.length > 0 ? (
                      <ul className="space-y-2">
                        {tips.map((tip, idx) => (
                          <li
                            key={tip}
                            className="flex items-start gap-2 bg-amber-50 border border-amber-100 rounded-lg p-3"
                          >
                            <span className="mt-0.5 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-amber-200 text-xs font-semibold text-amber-800">
                              {idx + 1}
                            </span>
                            <span className="text-sm text-slate-700">{tip}</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <div className="bg-green-50 border border-green-200 rounded-lg p-3">
                        <p className="text-xs text-green-800 font-medium">
                          La consulta es suficientemente completa. No se detectó información
                          relevante faltante.
                        </p>
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
