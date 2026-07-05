import { motion } from 'framer-motion';

interface LoadingAnimationProps {
  useAI: boolean;
}

// Componente SVG cardio personalizado
function CardioIcon({ useAI }: Readonly<{ useAI: boolean }>) {
  const color = useAI ? '#a855f7' : '#2563eb'; // púrpura si usa IA, azul si no
  
  return (
    <svg
      width="50"
      height="50"
      viewBox="0 0 50 50"
      style={{ color }}
    >
      <motion.g
        initial={{ opacity: 0.3 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 1, repeat: Infinity, repeatType: 'reverse', ease: 'easeInOut' }}
      >
        {/* Corazón base */}
        <path
          d="M25 40 C10 30, 5 20, 5 15 C5 8, 10 3, 15 3 C19 3, 23 6, 25 10 C27 6, 31 3, 35 3 C40 3, 45 8, 45 15 C45 20, 40 30, 25 40Z"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        />
        {/* Línea de pulso */}
        <motion.path
          d="M 8 25 L 15 25 L 18 15 L 22 35 L 25 25 L 32 25"
          stroke="currentColor"
          strokeWidth="1.5"
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: 2, repeat: Infinity }}
        />
      </motion.g>
    </svg>
  );
}

export function LoadingAnimation({ useAI }: Readonly<LoadingAnimationProps>) {

  const baseColor = useAI ? 'from-purple-400 to-purple-600' : 'from-blue-400 to-blue-600';
  const textColor = useAI ? 'text-purple-700' : 'text-slate-700';

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.5 }}
      className="bg-white rounded-xl border border-slate-200 p-8"
    >
      {/* Encabezado principal */}
      <div className="flex items-center justify-center gap-4 mb-6">
        <div className="w-12 h-12 flex items-center justify-center">
          <CardioIcon useAI={useAI} />
        </div>
        <div className="flex flex-col">
          <p className={`text-sm font-medium ${textColor}`}>
            {useAI ? 'Búsqueda, Clasificación y Análisis IA' : 'Búsqueda y Clasificación'}
          </p>
          <p className="text-xs text-slate-500">
            {useAI ? 'Procesando diagnóstico con inteligencia artificial...' : 'Procesando diagnóstico...'}
          </p>
        </div>
      </div>

      {/* Barras de progreso - color dinámico según IA */}
      <div className="space-y-2">
        {[0.2, 0.5, 0.8].map((delay) => (
          <motion.div
            key={delay}
            initial={{ width: '0%', opacity: 0.3 }}
            animate={{ width: '100%', opacity: 1 }}
            transition={{
              duration: 1.5,
              delay,
              repeat: Infinity,
              repeatType: 'reverse',
            }}
            className={`h-2 bg-gradient-to-r ${baseColor} rounded-full`}
          />
        ))}
      </div>
    </motion.div>
  );
}
