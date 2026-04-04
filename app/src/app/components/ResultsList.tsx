import { FileSearch, List } from 'lucide-react';
import { ResultCard } from './ResultCard';
import { LoadingAnimation } from './LoadingAnimation';
import type { DiagnosisResult } from '../App';
import { motion } from 'framer-motion';

interface ResultsListProps {
  results: DiagnosisResult[];
  isLoading: boolean;
  useAI: boolean;
}

export function ResultsList({ results, isLoading, useAI }: ResultsListProps) {
  if (isLoading) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
      >
        <LoadingAnimation useAI={useAI} />
      </motion.div>
    );
  }

  if (results.length === 0) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="bg-white rounded-xl border border-slate-200 p-12 text-center"
      >
        <div className="inline-flex items-center justify-center w-16 h-16 bg-slate-100 rounded-full mb-4">
          <FileSearch className="w-8 h-8 text-slate-400" />
        </div>
        <h3 className="text-lg text-slate-900 font-medium mb-2">
          Esperando diagnóstico...
        </h3>
        <p className="text-sm text-slate-600">
          Introduce un diagnóstico médico en el campo de búsqueda para obtener la clasificación CIE-10-ES
        </p>
      </motion.div>
    );
  }

  const containerVariants = {
    hidden: { opacity: 0 },
    visible: {
      opacity: 1,
      transition: {
        staggerChildren: 0.1,
      },
    },
  };

  return (
    <div className="space-y-4">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        className="flex items-center justify-between mb-4"
      >
        <h2 className="text-lg text-slate-900 font-semibold flex items-center gap-2">
          <List className="w-5 h-5 text-slate-500" />
          Resultados de clasificación
        </h2>
        <span className="text-sm text-slate-600 bg-slate-100 px-2 py-1 rounded-md">
          {results.length} {results.length === 1 ? 'resultado' : 'resultados'}
        </span>
      </motion.div>

      <motion.div
        className="space-y-3"
        variants={containerVariants}
        initial="hidden"
        animate="visible"
      >
        {results.map((result, index) => (
          <ResultCard key={result.payload.id} result={result} rank={index + 1} />
        ))}
      </motion.div>
    </div>
  );
}
