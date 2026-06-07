import { useState } from 'react';
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogHeader,
  AlertDialogTitle,
} from './ui/alert-dialog';
import { Button } from './ui/button';
import { Alert, AlertDescription } from './ui/alert';
import { Badge } from './ui/badge';
import { AlertCircle, Ban, Clock, Globe, Loader2, ShieldCheck } from 'lucide-react';
import type { UserBlockInfo } from '../services/adminService';

interface UnblockUserDialogProps {
  open: boolean;
  username: string;
  blockInfo: UserBlockInfo | null;
  isLoadingInfo: boolean;
  isUnblocking: boolean;
  error: string | null;
  onOpenChange: (open: boolean) => void;
  onConfirm: (username: string) => Promise<void>;
}

/** Formatea una fecha ISO a una cadena legible en español. */
function formatDate(iso: string | null): string {
  if (!iso) return 'Fecha desconocida';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return 'Fecha desconocida';
  return date.toLocaleString('es-ES', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export function UnblockUserDialog({
  open,
  username,
  blockInfo,
  isLoadingInfo,
  isUnblocking,
  error,
  onOpenChange,
  onConfirm,
}: UnblockUserDialogProps) {
  const [localError, setLocalError] = useState<string | null>(null);

  const handleConfirm = async () => {
    try {
      setLocalError(null);
      await onConfirm(username);
      // Éxito: el usuario desaparece del estado bloqueado al recargar la tabla.
      onOpenChange(false);
    } catch (err) {
      // El error lo muestra el padre (prop error); mantenemos el diálogo abierto.
      if (err instanceof Error) {
        setLocalError(err.message);
      }
    }
  };

  const handleOpenChange = (newOpen: boolean) => {
    if (!newOpen && (isUnblocking || isLoadingInfo)) {
      return; // No cerrar mientras hay una operación en curso
    }
    if (!newOpen) {
      setLocalError(null);
    }
    onOpenChange(newOpen);
  };

  const failedAttempts = blockInfo?.failed_attempts ?? [];
  const blockCount = blockInfo?.block_count ?? 0;
  const displayError = error ?? localError;

  return (
    <AlertDialog open={open} onOpenChange={handleOpenChange}>
      <AlertDialogContent className="max-w-lg">
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2 text-red-600">
            <Ban className="w-5 h-5" />
            Desbloquear usuario
          </AlertDialogTitle>
          <AlertDialogDescription>
            El usuario <strong>{username}</strong> está bloqueado tras varios
            intentos fallidos de inicio de sesión. Revisa los intentos y, si lo
            consideras seguro, restablece su acceso.
          </AlertDialogDescription>
        </AlertDialogHeader>

        {/* Resumen del bloqueo */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="rounded-lg border border-red-200 bg-red-50 p-3">
            <div className="flex items-center gap-2 text-xs font-medium text-red-700">
              <Ban className="w-3.5 h-3.5" />
              Veces bloqueado
            </div>
            <div className="mt-1 text-2xl font-bold text-red-700">{blockCount}</div>
            <div className="text-xs text-red-600/80">por intentos fallidos</div>
          </div>
          <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
            <div className="flex items-center gap-2 text-xs font-medium text-gray-600">
              <Globe className="w-3.5 h-3.5" />
              IP bloqueada
            </div>
            <div className="mt-1 text-sm font-semibold text-gray-800 break-all">
              {blockInfo?.current_block?.ip_address ?? 'N/D'}
            </div>
            {blockInfo?.current_block?.blocked_at && (
              <div className="text-xs text-gray-500">
                Desde {formatDate(blockInfo.current_block.blocked_at)}
              </div>
            )}
          </div>
        </div>

        {/* Lista de intentos fallidos */}
        <div>
          <div className="mb-2 flex items-center justify-between">
            <h4 className="text-sm font-medium text-gray-700">
              Inicios de sesión fallidos
            </h4>
            {!isLoadingInfo && (
              <Badge className="bg-gray-100 text-gray-600 hover:bg-gray-100">
                {failedAttempts.length}
              </Badge>
            )}
          </div>

          {isLoadingInfo ? (
            <div className="flex items-center justify-center gap-2 py-8 text-sm text-gray-500">
              <Loader2 className="w-4 h-4 animate-spin" />
              Cargando intentos...
            </div>
          ) : failedAttempts.length === 0 ? (
            <div className="rounded-lg border border-dashed border-gray-200 py-6 text-center text-sm text-gray-500">
              No hay intentos fallidos registrados.
            </div>
          ) : (
            <div className="max-h-56 overflow-y-auto rounded-lg border border-gray-200 divide-y divide-gray-100">
              {failedAttempts.map((attempt, idx) => (
                <div
                  key={`${attempt.timestamp}-${idx}`}
                  className="flex items-center justify-between gap-3 px-3 py-2 text-sm"
                >
                  <div className="flex items-center gap-2 text-gray-700">
                    <Clock className="w-3.5 h-3.5 text-gray-400 shrink-0" />
                    <span>{formatDate(attempt.timestamp)}</span>
                  </div>
                  <div className="flex items-center gap-1.5 text-xs text-gray-500">
                    <Globe className="w-3 h-3 shrink-0" />
                    <span className="break-all">{attempt.ip_address ?? 'IP desconocida'}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {displayError && (
          <Alert variant="destructive">
            <AlertCircle className="w-4 h-4" />
            <AlertDescription>{displayError}</AlertDescription>
          </Alert>
        )}

        <div className="flex gap-2 justify-end">
          <AlertDialogCancel disabled={isUnblocking || isLoadingInfo}>
            Cancelar
          </AlertDialogCancel>
          <Button
            onClick={handleConfirm}
            disabled={isUnblocking || isLoadingInfo}
            className="gap-2 bg-green-600 hover:bg-green-700 text-white"
          >
            {isUnblocking ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Desbloqueando...
              </>
            ) : (
              <>
                <ShieldCheck className="w-4 h-4" />
                Desbloquear acceso
              </>
            )}
          </Button>
        </div>
      </AlertDialogContent>
    </AlertDialog>
  );
}
