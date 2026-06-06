/**
 * Utilidades de desplazamiento (scroll) suave y sincronizado.
 *
 * A diferencia de `scrollIntoView`, que se invoca después de que un elemento
 * termina su animación (lo que produce un movimiento brusco en dos fases),
 * estas utilidades animan el scroll de la ventana en paralelo con la animación
 * del elemento, de modo que ambos se muevan "al compás".
 */

/** Curva de easing por defecto (easeInOutCubic), igual sensación que las animaciones. */
const easeInOutCubic = (t: number): number =>
  t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

/**
 * Anima el scroll vertical de la ventana hasta `targetY` durante `duration` ms.
 * Usa requestAnimationFrame para que el movimiento sea fluido y se pueda
 * sincronizar con la duración de una animación de framer-motion.
 */
export function animateScrollTo(
  targetY: number,
  duration = 400,
  easing: (t: number) => number = easeInOutCubic
): void {
  if (typeof window === 'undefined') return;

  const startY = window.scrollY;

  // Computar diff contra el targetY sin acotar por maxScroll. Esto es
  // intencional: cuando se expande el último elemento la página aún no tiene
  // espacio de scroll pero, a medida que framer-motion anima la altura, el
  // documento crece y el navegador puede ir scrollando hasta la meta.
  const diff = targetY - startY;

  if (Math.abs(diff) < 1 || duration <= 0) {
    // Para el scroll inmediato sí acotamos para no exceder los límites actuales.
    const maxScroll = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
    window.scrollTo(0, Math.max(0, Math.min(targetY, maxScroll)));
    return;
  }

  let startTime: number | null = null;

  const step = (timestamp: number) => {
    if (startTime === null) startTime = timestamp;
    const elapsed = timestamp - startTime;
    const progress = Math.min(elapsed / duration, 1);
    // El navegador acota el scroll a los límites del documento de forma
    // natural; a medida que el elemento se expande, el documento crece y
    // permite alcanzar posiciones antes inalcanzables.
    window.scrollTo(0, Math.max(0, startY + diff * easing(progress)));
    if (progress < 1) {
      requestAnimationFrame(step);
    }
  };

  requestAnimationFrame(step);
}

/**
 * Calcula el desplazamiento necesario y anima el scroll para que el borde
 * inferior previsto de un elemento (su posición actual + una altura extra que
 * va a aparecer al expandirse) quede visible dentro del viewport, manteniendo
 * un margen. El movimiento se realiza en paralelo a la animación de expansión.
 *
 * @param element        Elemento de referencia (p. ej. la tarjeta).
 * @param extraHeight    Altura adicional que el elemento alcanzará al animarse.
 * @param duration       Duración de la animación de scroll (ms).
 * @param margin         Margen mínimo respecto a los bordes del viewport (px).
 */
export function scrollToRevealExpansion(
  element: HTMLElement,
  extraHeight: number,
  duration = 400,
  margin = 24
): void {
  if (typeof window === 'undefined') return;

  const rect = element.getBoundingClientRect();
  const viewportHeight = window.innerHeight;
  const predictedBottom = rect.bottom + extraHeight;

  let delta = 0;
  if (predictedBottom > viewportHeight - margin) {
    delta = predictedBottom - (viewportHeight - margin);
    // No desplazar tanto que el borde superior del elemento quede por encima
    // del margen superior; así no perdemos de vista la cabecera del elemento.
    const maxUp = Math.max(0, rect.top - margin);
    delta = Math.min(delta, maxUp);
  }

  if (delta > 1) {
    animateScrollTo(window.scrollY + delta, duration);
  }
}
