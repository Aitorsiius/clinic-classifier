import { ChevronRight, Copy, Check } from 'lucide-react';
import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

interface AIAnalysis {
  original_query: string;
  corrected_query: string;
  analysis: {
    primary_symptoms: string[];
    secondary_symptoms: string[];
    key_findings: string[];
    search_keywords: string[];
    clinical_context: string;
  };
  processing_time_ms: number;
}

interface AIAnalysisPanelProps {
  data: AIAnalysis;
  shouldCollapse?: boolean;
}

export function AIAnalysisPanel({ data, shouldCollapse = false }: AIAnalysisPanelProps) {
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

  function capitalize(str: string): string {
    return str.charAt(0).toUpperCase() + str.slice(1);
  }

  const cardVariants = {
    hidden: { opacity: 0, y: 20 },
    visible: { opacity: 1, y: 0, transition: { duration: 0.4 } },
  };

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
              💡 Este análisis es un asistente independiente para ayudarte a encontrar el código CIE-10 ES correcto. 
              No afecta la clasificación automática de resultados.
            </p>
          </div>

          {/* Validar si hay datos de análisis válidos */}
          {!data.analysis || 
           (!data.corrected_query && 
            (!data.analysis.primary_symptoms || data.analysis.primary_symptoms.length === 0) &&
            (!data.analysis.secondary_symptoms || data.analysis.secondary_symptoms.length === 0) &&
            (!data.analysis.search_keywords || data.analysis.search_keywords.length === 0)) ? (
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-6 text-center">
              <p className="text-sm font-medium text-amber-800 mb-2">⚠️ No se pudo analizar el diagnóstico</p>
              <p className="text-xs text-amber-700">
                El texto del diagnóstico proporcionado es demasiado pobre o no contiene información médica suficiente para realizar un análisis detallado. 
                Intenta con una descripción más completa.
              </p>
            </div>
          ) : (
            <>
          {/* Consulta Original vs Normalizada */}
          <div className="space-y-2">
            <div className="text-sm font-semibold text-slate-600">Consulta Original:</div>
            <div className="bg-white rounded-lg p-3 border border-slate-200">
              <p className="text-sm text-slate-700 whitespace-pre-wrap break-words">{data.original_query}</p>
            </div>
          </div>

          {/* Análisis Clínico - Síntomas */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Síntomas Primarios */}
            {data.analysis.primary_symptoms && data.analysis.primary_symptoms.length > 0 && (
              <div className="bg-white rounded-lg p-3 border border-slate-200">
                <p className="text-xs font-semibold text-red-600 mb-2">Síntomas Primarios:</p>
                <ul className="space-y-1">
                  {data.analysis.primary_symptoms.map((symptom, idx) => (
                    <li key={idx} className="text-sm text-slate-700 flex items-center justify-start gap-2">
                      <span className="text-red-500 flex-shrink-0 text-center w-4">•</span>
                      <span>{capitalize(symptom)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Síntomas Secundarios */}
            {data.analysis.secondary_symptoms && data.analysis.secondary_symptoms.length > 0 && (
              <div className="bg-white rounded-lg p-3 border border-slate-200">
                <p className="text-xs font-semibold text-amber-600 mb-2">Síntomas Secundarios:</p>
                <ul className="space-y-1">
                  {data.analysis.secondary_symptoms.map((symptom, idx) => (
                    <li key={idx} className="text-sm text-slate-700 flex items-center justify-start gap-2">
                      <span className="text-amber-500 flex-shrink-0 text-center w-4">•</span>
                      <span>{capitalize(symptom)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Contexto Clínico - ELIMINADO */}
          </div>

          {/* Consulta Mejorada / Normalizada */}
          {data.corrected_query && data.corrected_query !== data.original_query && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold text-slate-600">Consulta Mejorada:</div>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleCopy(data.corrected_query, 'improved-query');
                  }}
                  className="flex items-center gap-1.5 px-2 py-1 text-xs font-medium rounded bg-purple-100 text-purple-700 hover:bg-purple-200 transition-colors"
                >
                  {copiedText === 'improved-query' ? (
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
                <p className="text-sm text-slate-700 whitespace-pre-wrap break-words">{data.corrected_query}</p>
              </div>
            </div>
          )}

          {/* Palabras Clave */}
          {data.analysis.search_keywords && data.analysis.search_keywords.length > 0 && (
            <div className="space-y-2">
              <div className="text-sm font-semibold text-slate-600">Palabras Clave para Búsqueda:</div>
              <div className="flex flex-wrap gap-2">
                {data.analysis.search_keywords.map((keyword, idx) => (
                  <span
                    key={idx}
                    className="inline-block bg-purple-100 text-purple-700 text-xs font-medium px-3 py-1 rounded-full border border-purple-200"
                  >
                    {capitalize(keyword)}
                  </span>
                ))}
              </div>
            </div>
          )}
            </>
          )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
