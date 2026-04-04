import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';

interface AnimatedProcessButtonProps {
  onClick: () => void;
  isProcessing: boolean;
  disabled?: boolean;
  progress?: number; // 0-100, si no se proporciona usa animación automática
  label?: string;
}

export function AnimatedProcessButton({
  onClick,
  isProcessing,
  disabled = false,
  progress: externalProgress,
  label = 'Iniciar Auditoría',
}: AnimatedProcessButtonProps) {
  const [progress, setProgress] = useState(0);

  // Si se proporciona progreso externo, úsalo; si no, usa animación automática
  useEffect(() => {
    if (externalProgress !== undefined) {
      setProgress(Math.min(externalProgress, 100));
      return;
    }

    if (!isProcessing) {
      setProgress(0);
      return;
    }

    // Animación automática (sin progreso real)
    const interval = setInterval(() => {
      setProgress((prev) => {
        // Incremento gradual que se ralentiza hacia el 100%
        const increment = Math.random() * 15 + (90 - prev) * 0.05;
        const newProgress = Math.min(prev + increment, 99);
        return newProgress;
      });
    }, 500);

    return () => clearInterval(interval);
  }, [isProcessing, externalProgress]);

  // Cuando termina el procesamiento
  useEffect(() => {
    if (!isProcessing && progress > 0 && externalProgress === undefined) {
      setProgress(100);
      const timer = setTimeout(() => setProgress(0), 600);
      return () => clearTimeout(timer);
    }
  }, [isProcessing, progress, externalProgress]);

  return (
    <button
      onClick={onClick}
      disabled={disabled || isProcessing}
      className="relative w-full px-6 py-3 bg-blue-600 hover:bg-blue-700 disabled:bg-opacity-100 disabled:bg-blue-900 disabled:cursor-not-allowed text-white rounded-lg font-medium transition-all overflow-hidden group"
    >
      {/* Barra de progreso con efecto de agua */}
      {isProcessing && (
        <motion.div
          className="absolute left-0 top-0 bottom-0 bg-cyan-500 overflow-hidden"
          animate={{
            width: `${progress}%`,
          }}
          transition={{
            duration: 0.3,
            ease: 'easeOut',
          }}
        >
          {/* Ola frontal */}
          <motion.div 
            className="absolute top-0 bottom-0 w-[200px] opacity-40 bg-cyan-300 pointer-events-none"
            style={{ 
              right: '-100px', 
              borderRadius: '45%', 
              scale: 2 
            }}
            animate={{ 
              rotate: 360,
              y: ['-5%', '5%', '-5%']
            }}
            transition={{ 
              rotate: { duration: 3, repeat: Infinity, ease: "linear" },
              y: { duration: 2, repeat: Infinity, ease: "easeInOut" }
            }}
          />
          {/* Ola trasera */}
          <motion.div 
            className="absolute top-0 bottom-0 w-[220px] opacity-30 bg-cyan-200 pointer-events-none"
            style={{ 
              right: '-110px', 
              borderRadius: '40%', 
              scale: 2.2 
            }}
            animate={{ 
              rotate: -360,
            }}
            transition={{ 
              duration: 4, 
              repeat: Infinity, 
              ease: "linear" 
            }}
          />
          <div className="absolute inset-0 bg-cyan-500 opacity-50 z-10" />
        </motion.div>
      )}

      {/* Contenido del botón */}
      <div className="relative flex items-center justify-center gap-2">
        {isProcessing && (
          <motion.div
            animate={{
              rotate: 360,
            }}
            transition={{
              duration: 1,
              repeat: Infinity,
              ease: 'linear',
            }}
            className="w-4 h-4"
          >
            <svg
              className="w-4 h-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
              />
            </svg>
          </motion.div>
        )}
        <span className="text-sm">
          {isProcessing 
            ? `Procesando... ${externalProgress !== undefined ? `${Math.round(progress)}%` : ''}` 
            : label}
        </span>
      </div>
    </button>
  );
}
