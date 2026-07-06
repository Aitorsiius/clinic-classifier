// Icono de reloj con agujas animables de forma independiente.

interface HistoryClockIconProps {
  className?: string;
}

export function HistoryClockIcon({ className }: Readonly<HistoryClockIconProps>) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {/* Esfera del reloj */}
      <circle cx="12" cy="12" r="9" />
      {/* Aguja de la hora (corta): acompaña a la de los minutos a 1/12 de vuelta */}
      <line className="clock-hand clock-hand--hour" x1="12" y1="12" x2="12" y2="8.5" />
      {/* Aguja de los minutos (larga): da un par de vueltas al pasar el ratón */}
      <line className="clock-hand clock-hand--minute" x1="12" y1="12" x2="12" y2="6" />
      {/* Eje central */}
      <circle cx="12" cy="12" r="0.9" fill="currentColor" stroke="none" />
    </svg>
  );
}
