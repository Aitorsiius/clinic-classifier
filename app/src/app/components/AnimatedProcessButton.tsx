import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { formatElapsedSeconds } from '../utils/format';

// Configuración de las burbujas que ascienden por el agua (posición, tamaño,
// altura de ascenso, deriva horizontal, duración y retardo de cada una).
const BUBBLES = [
  { id: 'b1', left: 10, size: 6, rise: 40, drift: 4, duration: 2.8, delay: 0 },
  { id: 'b2', left: 24, size: 4, rise: 38, drift: -3, duration: 2.2, delay: 0.7 },
  { id: 'b3', left: 40, size: 7, rise: 42, drift: 5, duration: 3.3, delay: 1.2 },
  { id: 'b4', left: 55, size: 5, rise: 39, drift: -4, duration: 2.6, delay: 0.4 },
  { id: 'b5', left: 70, size: 4, rise: 41, drift: 3, duration: 3, delay: 1.5 },
  { id: 'b6', left: 85, size: 6, rise: 37, drift: -5, duration: 2.4, delay: 0.9 },
];

interface AnimatedProcessButtonProps {
  onClick: () => void;
  isProcessing: boolean;
  disabled?: boolean;
  progress?: number; // 0-100, si no se proporciona usa animación automática
  label?: string;
  // Marca de tiempo (ms epoch) de inicio del proceso. Si se proporciona, el
  // botón muestra un cronómetro en vivo "(X.Xs)" junto al porcentaje.
  startTime?: number | null;
}

export function AnimatedProcessButton({
  onClick,
  isProcessing,
  disabled = false,
  progress: externalProgress,
  label = 'Iniciar Auditoría',
  startTime,
}: Readonly<AnimatedProcessButtonProps>) {
  const [progress, setProgress] = useState(0);  
  // Tiempo transcurrido (ms) desde startTime, refrescado periódicamente para
  // animar el cronómetro mientras dura el proceso.
  const [elapsedMs, setElapsedMs] = useState(0);

  // Cronómetro en vivo: mientras se procesa y haya startTime, refresca el
  // tiempo transcurrido cada 100 ms. Al parar, congela el último valor.
  //
  // El tiempo SIEMPRE se calcula como `Date.now() - startTime` (reloj de
  // pared), nunca acumulando ticks: aunque el navegador ralentice o congele
  // el setInterval cuando la pestaña pasa a segundo plano, en cuanto vuelve a
  // ejecutarse muestra el tiempo real transcurrido. El listener de
  // `visibilitychange` fuerza ese recálculo en el instante en que el usuario
  // regresa a la pestaña, sin esperar al siguiente tick.
  useEffect(() => {
    if (!isProcessing || !startTime) {
      return;
    }
    const tick = () => setElapsedMs(Date.now() - startTime);
    tick();
    const interval = setInterval(tick, 100);
    const handleVisibility = () => {
      if (document.visibilityState === 'visible') tick();
    };
    document.addEventListener('visibilitychange', handleVisibility);
    return () => {
      clearInterval(interval);
      document.removeEventListener('visibilitychange', handleVisibility);
    };
  }, [isProcessing, startTime]);

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

  const percentText = externalProgress === undefined ? '' : `${Math.round(progress)}%`;
  const elapsedText = startTime ? ` (${formatElapsedSeconds(elapsedMs)})` : '';
  const buttonText = isProcessing ? `Procesando... ${percentText}${elapsedText}` : label;

  return (
    <button
      onClick={onClick}
      disabled={disabled || isProcessing}
      className="group relative w-full overflow-hidden rounded-xl px-6 py-3 font-medium text-white bg-gradient-to-r from-blue-600 to-indigo-600 shadow-lg shadow-blue-600/25 transition-all duration-200 hover:-translate-y-0.5 hover:from-blue-700 hover:to-indigo-700 hover:shadow-xl hover:shadow-blue-600/30 active:translate-y-0 active:scale-[0.98] disabled:translate-y-0 disabled:cursor-not-allowed disabled:from-blue-800 disabled:to-indigo-900 disabled:shadow-md"
    >
      {/* Barra de progreso con efecto de agua */}
      {isProcessing && (
        <motion.div
          className="pointer-events-none absolute inset-y-0 left-0 overflow-hidden"
          animate={{ width: `${progress}%` }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
        >
          {/* Cuerpo del agua con degradado de profundidad */}
          <div className="absolute inset-0 bg-gradient-to-b from-cyan-300 via-cyan-400 to-blue-500" />

          {/* Brillo suave de la superficie */}
          <div className="absolute inset-x-0 top-0 h-1/2 bg-gradient-to-b from-white/25 to-transparent" />

          {/* Ola trasera (lenta, efecto parallax) */}
          <motion.div
            className="absolute inset-y-0 left-0 h-full"
            style={{ width: '200%' }}
            animate={{ x: ['0%', '-50%'] }}
            transition={{ duration: 6, repeat: Infinity, ease: 'linear' }}
          >
            <svg className="h-full w-full" viewBox="0 0 1200 100" preserveAspectRatio="none">
              <path
                d="M0,24 Q75,8 150,24 Q225,40 300,24 Q375,8 450,24 Q525,40 600,24 Q675,8 750,24 Q825,40 900,24 Q975,8 1050,24 Q1125,40 1200,24 L1200,100 L0,100 Z"
                fill="rgba(165,243,252,0.35)"
              />
            </svg>
          </motion.div>

          {/* Ola frontal (rápida, efecto parallax) */}
          <motion.div
            className="absolute inset-y-0 left-0 h-full"
            style={{ width: '200%' }}
            animate={{ x: ['0%', '-50%'] }}
            transition={{ duration: 3.2, repeat: Infinity, ease: 'linear' }}
          >
            <svg className="h-full w-full" viewBox="0 0 1200 100" preserveAspectRatio="none">
              <path
                d="M0,30 Q50,14 100,30 Q150,46 200,30 Q250,14 300,30 Q350,46 400,30 Q450,14 500,30 Q550,46 600,30 Q650,14 700,30 Q750,46 800,30 Q850,14 900,30 Q950,46 1000,30 Q1050,14 1100,30 Q1150,46 1200,30 L1200,100 L0,100 Z"
                fill="rgba(207,250,254,0.5)"
              />
            </svg>
          </motion.div>

          {/* Burbujas que ascienden */}
          {BUBBLES.map((b) => (
            <motion.span
              key={b.id}
              className="absolute rounded-full bg-white/60"
              style={{
                left: `${b.left}%`,
                width: b.size,
                height: b.size,
                bottom: -b.size,
              }}
              animate={{ y: [0, -b.rise], x: [0, b.drift, 0], opacity: [0, 0.7, 0] }}
              transition={{
                duration: b.duration,
                repeat: Infinity,
                delay: b.delay,
                ease: 'easeInOut',
              }}
            />
          ))}

          {/* Brillo en el borde de avance del agua */}
          <div className="absolute inset-y-0 right-0 w-2 bg-white/30 blur-[2px]" />
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
          {buttonText}
        </span>
      </div>
    </button>
  );
}
