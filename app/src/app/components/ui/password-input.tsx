import * as React from 'react';
import { useState, useCallback } from 'react';
import { Eye, EyeOff } from 'lucide-react';

import { Input } from './input';
import { cn } from './utils';

interface PasswordInputProps extends React.ComponentProps<'input'> {
  /** Icono opcional a mostrar a la izquierda del campo (p. ej. un candado). */
  leftIcon?: React.ReactNode;
}

/**
 * Campo de contraseña con un botón de "ojo" a la derecha.
 *
 * La contraseña solo se muestra mientras el usuario mantiene pulsado el icono
 * (con ratón o táctil); al soltar, vuelve a ocultarse. Esto evita revelados
 * accidentales y mantiene la contraseña visible únicamente bajo demanda.
 */
export function PasswordInput({
  className,
  leftIcon,
  disabled,
  ...props
}: Readonly<PasswordInputProps>) {
  const [visible, setVisible] = useState(false);

  const show = useCallback(() => setVisible(true), []);
  const hide = useCallback(() => setVisible(false), []);

  return (
    <div className="relative">
      {leftIcon && (
        <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-gray-400">
          {leftIcon}
        </span>
      )}

      <Input
        {...props}
        disabled={disabled}
        type={visible ? 'text' : 'password'}
        className={cn(leftIcon ? 'pl-10' : '', 'pr-11', className)}
      />

      <button
        type="button"
        // Mantener pulsado para revelar; soltar (o salir) para ocultar
        onMouseDown={show}
        onMouseUp={hide}
        onMouseLeave={hide}
        onTouchStart={(e) => {
          e.preventDefault();
          show();
        }}
        onTouchEnd={hide}
        onTouchCancel={hide}
        onContextMenu={(e) => e.preventDefault()}
        disabled={disabled}
        tabIndex={-1}
        aria-label={visible ? 'Ocultar contraseña' : 'Mostrar contraseña (mantén pulsado)'}
        title="Mantén pulsado para ver la contraseña"
        className="absolute right-1.5 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600 disabled:pointer-events-none disabled:opacity-50"
      >
        {visible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </button>
    </div>
  );
}
