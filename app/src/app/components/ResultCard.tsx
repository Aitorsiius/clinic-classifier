import { useState } from 'react';
import { ChevronRight, Smile, Meh, Frown, ChevronsRight, Copy, Check } from 'lucide-react';
import type { DiagnosisResult } from '../App';
import { motion, AnimatePresence } from 'framer-motion';

interface ResultCardProps {
  result: DiagnosisResult;
  rank: number;
}

export function ResultCard({ result, rank }: ResultCardProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [copiedCode, setCopiedCode] = useState<string | null>(null);
  const { score, payload } = result;
  const scaledScore = score <= 1 ? score * 10 : score; // Escalar si viene normalizado (0-1)
  const { id, title, metadata = {} } = payload;

  const handleCopyCode = async (e: React.MouseEvent, code: string) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(code);
      setCopiedCode(code);
      setTimeout(() => setCopiedCode(null), 2000);
    } catch (err) {
      console.error('Error copying to clipboard:', err);
    }
  };

  // Determinar color del badge según el score
  const getConfidenceBadge = (score: number) => {
    if (score >= 7) {
      return {
        bg: 'bg-green-100',
        text: 'text-green-800',
        border: 'border-green-200',
        label: 'Alta confianza',
        icon: Smile
      };
    } else if (score >= 4) {
      return {
        bg: 'bg-yellow-100',
        text: 'text-yellow-800',
        border: 'border-yellow-200',
        label: 'Confianza media',
        icon: Meh
      };
    } else {
      return {
        bg: 'bg-orange-100',
        text: 'text-orange-800',
        border: 'border-orange-200',
        label: 'Confianza baja',
        icon: Frown
      };
    }
  };

  const confidenceBadge = getConfidenceBadge(scaledScore);

  const cardVariants = {
    hidden: { opacity: 0, y: 20 },
    visible: { opacity: 1, y: 0, transition: { duration: 0.4 } },
  };

  const contentVariants = {
    collapsed: { height: 0, opacity: 0 },
    expanded: { height: 'auto', opacity: 1, transition: { duration: 0.4, ease: 'easeInOut' } },
  };

  const handleToggleExpand = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsOpen(!isOpen);
  };

  return (
    <motion.div
      variants={cardVariants}
      layout
      className="bg-white rounded-lg border border-slate-200 shadow-sm hover:shadow-lg transition-all duration-300 p-5 hover:border-blue-300 cursor-pointer"
      onClick={handleToggleExpand}
    >
      <motion.div layout="position" className="flex items-start justify-between pointer-events-none">
        <div className="flex items-start gap-4 flex-1">
          <div className="flex items-center justify-center w-10 h-10 bg-slate-100 rounded-full text-base font-semibold text-slate-700 flex-shrink-0 mt-0.5">
            {rank}
          </div>
          
          <div className="flex-1">
            <div className="flex items-center flex-wrap gap-3 mb-2">
              <button
                onClick={(e) => handleCopyCode(e, id)}
                className="group relative text-xl font-bold text-blue-700 bg-blue-50 px-3 py-1 rounded border border-blue-200 hover:bg-blue-100 hover:border-blue-300 transition-colors cursor-pointer pointer-events-auto"
              >
                {id}
                <span className="absolute -top-8 left-1/2 -translate-x-1/2 bg-slate-900 text-white text-xs px-2 py-1 rounded whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none">
                  {copiedCode === id ? '¡Copiado!' : 'Click para copiar'}
                </span>
              </button>
              
              <div className={`flex items-center gap-1.5 px-3 py-1 rounded-full border ${confidenceBadge.border} ${confidenceBadge.bg}`}>
                {confidenceBadge.icon && <confidenceBadge.icon className={`w-4 h-4 ${confidenceBadge.text}`} />}
                <span className={`text-sm font-medium ${confidenceBadge.text}`}>
                  {confidenceBadge.label}
                </span>
                <span className={`text-sm font-mono ${confidenceBadge.text}`}>
                  ({scaledScore.toFixed(1)})
                </span>
              </div>
            </div>
            
            <h3 className="text-base text-slate-900 leading-snug">
              {title}
            </h3>
          </div>
        </div>
        <motion.div animate={{ rotate: isOpen ? 90 : 0 }} className="pointer-events-none">
          <ChevronRight className="w-5 h-5 text-slate-500" />
        </motion.div>
      </motion.div>

      <AnimatePresence>
        {isOpen && (
          <motion.div
            variants={contentVariants}
            initial="collapsed"
            animate="expanded"
            exit="collapsed"
            className="overflow-hidden"
          >
            {/* Jerarquía / Trazabilidad */}
            {metadata && metadata.hierarchy && metadata.hierarchy.length > 0 ? (
              <div className="mt-6 pt-4 border-t border-slate-200">
                <h4 className="text-sm text-slate-800 mb-3 font-semibold flex items-center gap-2">
                  <ChevronsRight className="w-5 h-5 text-slate-400" />
                  Trazabilidad (Jerarquía CIE-10 ES)
                </h4>
                
                <div className="space-y-2 pl-2">
                  {metadata.hierarchy.map((level, index) => (
                    <div key={index} className="flex items-start" style={{ marginLeft: `${index * 1.5}rem` }}>
                      <div className="flex items-center gap-3">
                        <code className="text-sm font-mono text-slate-600 bg-slate-100 px-2 py-0.5 rounded">
                          {level.code}
                        </code>
                        <span className="text-sm text-slate-700">
                          {level.title}
                        </span>
                      </div>
                    </div>
                  ))}
                  {/* Código final */}
                  <div className="flex items-start" style={{ marginLeft: `${metadata.hierarchy.length * 1.5}rem` }}>
                    <div className="flex items-center gap-3">
                      <code className="text-sm font-bold text-blue-700 bg-blue-100 px-2 py-0.5 rounded">
                        {id}
                      </code>
                      <span className="text-sm font-semibold text-blue-800">
                        {title}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="mt-6 pt-4 border-t border-slate-200">
                <p className="text-sm text-slate-500 italic">
                  No hay información de trazabilidad disponible para este código.
                </p>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
