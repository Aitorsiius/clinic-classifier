import { useEffect, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import { AnimatePresence, motion } from 'framer-motion';
import {
  Clock,
  Search,
  ClipboardCheck,
  UserPlus,
  KeyRound,
  ShieldCheck,
  UserMinus,
  LockOpen,
  X,
  type LucideIcon,
} from 'lucide-react';

/**
 * Da formato a un intervalo en milisegundos como un texto legible.
 * Ej: 45000 -> "45 s", 154000 -> "2 min 34 s", 3725000 -> "1 h 02 min".
 */
function formatElapsed(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) {
    return `${hours} h ${String(minutes).padStart(2, '0')} min`;
  }
  if (minutes > 0) {
    return `${minutes} min ${String(seconds).padStart(2, '0')} s`;
  }
  return `${seconds} s`;
}

interface StatItem {
  key: string;
  label: string;
  value: string | number;
  icon: LucideIcon;
}

/**
 * Overlay global que se muestra durante el cierre de sesión.
 *
 * Cubre toda la aplicación con un desvanecimiento suave y muestra una pantalla
 * de despedida personalizada ("Hasta pronto, {nombre}.") junto con un resumen
 * de las estadísticas de la sesión. Las estadísticas aparecen con una animación
 * de "cartera que se abre": cada panel está unido al anterior y se despliega
 * hacia abajo girando sobre su borde superior (efecto billetera/tríptico).
 */
export function LogoutOverlay() {
  const { isLoggingOut, logoutSummary, skipLogoutDisplay } = useAuth();

  // Guarda los valores previos del body para restaurarlos exactamente
  const prevBodyRef = useRef({ overflow: '', paddingRight: '' });

  // Bloquear el scroll del body mientras el overlay es visible. Se compensa el
  // ancho de la barra de scroll para evitar el efecto de "expansión" del layout.
  useEffect(() => {
    if (!isLoggingOut) return;

    const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth;
    prevBodyRef.current = {
      overflow: document.body.style.overflow,
      paddingRight: document.body.style.paddingRight,
    };
    document.body.style.overflow = 'hidden';
    if (scrollbarWidth > 0) {
      document.body.style.paddingRight = `${scrollbarWidth}px`;
    }
    // No restaurar en el cleanup: se hace en onExitComplete para esperar a que
    // la animación de salida (fade-out 0.35 s) haya terminado del todo.
  }, [isLoggingOut]);

  // Se llama por AnimatePresence una vez que el fade-out del overlay concluye.
  // En ese momento ya es seguro devolver el scroll al estado original sin que
  // el usuario note el cambio de layout.
  const handleExitComplete = () => {
    document.body.style.overflow = prevBodyRef.current.overflow;
    document.body.style.paddingRight = prevBodyRef.current.paddingRight;
  };

  const stats = logoutSummary?.stats;

  const items: StatItem[] = logoutSummary
    ? [
        {
          key: 'time',
          label: 'Tiempo en sesión',
          value: formatElapsed(logoutSummary.elapsedMs),
          icon: Clock,
        },
        {
          key: 'searches',
          label: 'Búsquedas realizadas',
          value: stats?.searches ?? 0,
          icon: Search,
        },
        {
          key: 'audits',
          label: 'Auditorías realizadas',
          value: stats?.audits ?? 0,
          icon: ClipboardCheck,
        },
        {
          key: 'usersCreated',
          label: 'Usuarios creados',
          value: stats?.usersCreated ?? 0,
          icon: UserPlus,
        },
        {
          key: 'passwordsChanged',
          label: 'Contraseñas modificadas',
          value: stats?.passwordsChanged ?? 0,
          icon: KeyRound,
        },
        {
          key: 'roleChanges',
          label: 'Cambios de rol',
          value: stats?.roleChanges ?? 0,
          icon: ShieldCheck,
        },
        {
          key: 'usersDeleted',
          label: 'Usuarios eliminados',
          value: stats?.usersDeleted ?? 0,
          icon: UserMinus,
        },
        {
          key: 'usersUnblocked',
          label: 'Usuarios desbloqueados',
          value: stats?.usersUnblocked ?? 0,
          icon: LockOpen,
        },
      ].filter(
        // Ocultar contadores que estén a cero: solo el tiempo (string) se muestra siempre
        (item) => typeof item.value !== 'number' || item.value > 0
      )
    : [];

  // Retardo a partir del cual empiezan a desplegarse los paneles de la cartera
  const WALLET_START_DELAY = 0.55;
  const WALLET_STAGGER = 0.16;

  return (
    <AnimatePresence onExitComplete={handleExitComplete}>
      {isLoggingOut && (
        <motion.div
          key="logout-overlay"
          role="status"
          aria-live="polite"
          className="fixed inset-0 z-[200] flex items-center justify-center overflow-y-auto bg-gradient-to-br from-blue-50 via-white to-indigo-100 px-6 py-10"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.35, ease: 'easeInOut' }}
        >
          {/* Botón de cierre — grande y visible para que el usuario pueda
              saltar la pantalla de despedida cuando haya terminado de leerla */}
          <button
            onClick={skipLogoutDisplay}
            aria-label="Cerrar pantalla de despedida"
            className="absolute right-5 top-5 flex h-12 w-12 items-center justify-center rounded-full bg-white/80 text-slate-500 shadow-md backdrop-blur-sm transition-all hover:scale-110 hover:bg-white hover:text-slate-900 active:scale-95"
          >
            <X className="h-7 w-7" strokeWidth={2.5} />
          </button>

          {logoutSummary && (
            <div className="flex w-full max-w-md flex-col items-center">
              {/* Mascota + despedida */}
              <motion.div
                initial={{ opacity: 0, y: 14, scale: 0.96 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                transition={{ delay: 0.12, duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
                className="mb-8 flex flex-col items-center text-center"
              >
                <motion.img
                  src="/chinchilla_close.png"
                  alt=""
                  aria-hidden="true"
                  className="mb-4 h-20 w-20 object-contain drop-shadow-sm"
                  initial={{ rotate: -6 }}
                  animate={{ rotate: [-6, 4, 0] }}
                  transition={{ delay: 0.2, duration: 0.9, ease: 'easeInOut' }}
                />
                <h1 className="text-3xl font-bold tracking-tight text-slate-800 sm:text-4xl">
                  Hasta pronto,{' '}
                  <span className="text-blue-600">{logoutSummary.username}</span>.
                </h1>
                <p className="mt-2 text-sm text-slate-500">
                  Este es el resumen de tu sesión
                </p>
              </motion.div>

              {/* Cartera de estadísticas que se despliega panel a panel */}
              <div className="w-full" style={{ perspective: '1200px' }}>
                {items.map((item, i) => {
                  const Icon = item.icon;
                  const delay = WALLET_START_DELAY + i * WALLET_STAGGER;
                  const isFirst = i === 0;
                  const isLast = i === items.length - 1;

                  return (
                    <motion.div
                      key={item.key}
                      initial={{ rotateX: -90, opacity: 0 }}
                      animate={{ rotateX: 0, opacity: 1 }}
                      transition={{
                        rotateX: { type: 'spring', stiffness: 130, damping: 14, delay },
                        opacity: { duration: 0.3, delay },
                      }}
                      style={{
                        transformOrigin: 'top center',
                        transformStyle: 'preserve-3d',
                        willChange: 'transform',
                      }}
                      className={[
                        'flex items-center justify-between gap-4 border border-slate-200/80 bg-white/90 px-5 py-3.5 shadow-sm backdrop-blur-sm',
                        isFirst ? 'rounded-t-2xl' : 'border-t-0',
                        isLast ? 'rounded-b-2xl' : '',
                      ].join(' ')}
                    >
                      <div className="flex items-center gap-3">
                        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
                          <Icon className="h-5 w-5" />
                        </span>
                        <span className="text-sm font-medium text-slate-600">
                          {item.label}
                        </span>
                      </div>
                      <span className="text-lg font-bold tabular-nums text-slate-800">
                        {item.value}
                      </span>
                    </motion.div>
                  );
                })}
              </div>
            </div>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
