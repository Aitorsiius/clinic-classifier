import { useState } from 'react';
import { ChevronDown, SlidersHorizontal } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

interface FiltersProps {
  topK: number;
  setTopK: (value: number) => void;
  isLoading?: boolean;
}

export function Filters({ topK, setTopK, isLoading = false }: Readonly<FiltersProps>) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="mb-4">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 text-sm font-medium text-slate-600 hover:text-slate-900 transition-colors focus:outline-none group"
      >
        <SlidersHorizontal className="w-4 h-4" />
        Filtros
        <ChevronDown 
          className={`w-4 h-4 transition-transform duration-200 ${isOpen ? 'rotate-180' : ''} text-slate-400 group-hover:text-slate-600`} 
        />
      </button>

      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="pt-4 pb-2 px-1 grid grid-cols-1 gap-6">
              {/* Slider de Resultados (Top K) */}
              <div className="flex flex-col h-full">
                <div className="flex justify-between items-center mb-2">
                  <label htmlFor="top-k-slider" className="block text-sm font-medium text-slate-700">
                    Número de resultados
                  </label>
                  <span className="text-sm font-mono font-medium text-blue-600 bg-blue-50 px-2 py-0.5 rounded border border-blue-100">
                    {topK}
                  </span>
                </div>
                
                <div className="flex items-center gap-4 flex-1 flex-col justify-start">
                  <div className="flex items-center gap-4 w-full">
                    <span className="text-xs text-slate-400">1</span>
                    <input
                      id="top-k-slider"
                      type="range"
                      min="1"
                      max="20"
                      step="1"
                      value={topK}
                      onChange={(e) => setTopK(Number.parseInt(e.target.value))}
                      disabled={isLoading}
                      className="w-full h-2 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-500/50 disabled:opacity-50 disabled:cursor-not-allowed"
                    />
                    <span className="text-xs text-slate-400">20</span>
                  </div>
                </div>
                <p className="text-xs text-slate-500 mt-2">
                  Cantidad máxima de resultados a mostrar.
                </p>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
