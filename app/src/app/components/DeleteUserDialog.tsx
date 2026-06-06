import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogHeader, AlertDialogTitle } from './ui/alert-dialog';
import { Alert, AlertDescription } from './ui/alert';
import { AlertCircle } from 'lucide-react';

interface DeleteUserDialogProps {
  open: boolean;
  username: string;
  onOpenChange: (open: boolean) => void;
  onConfirm: (username: string) => Promise<void>;
  isLoading: boolean;
  error: string | null;
}

export function DeleteUserDialog({
  open,
  username,
  onOpenChange,
  onConfirm,
  isLoading,
  error
}: DeleteUserDialogProps) {
  const handleConfirm = async () => {
    try {
      await onConfirm(username);
      // Borrado correcto: cerramos el diálogo. El usuario desaparece de la tabla,
      // lo que sirve de confirmación visual. No usamos estado de "éxito" ni
      // temporizadores: un cierre diferido podía cerrar un diálogo reabierto
      // rápidamente para otro usuario y dejar su botón deshabilitado.
      onOpenChange(false);
    } catch (err) {
      // Si falla, mantenemos el diálogo abierto; el error lo muestra el padre.
    }
  };

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent className="max-w-md">
        <AlertDialogHeader>
          <AlertDialogTitle className="text-red-600">Eliminar usuario</AlertDialogTitle>
          <AlertDialogDescription>
            ¿Estás seguro de que deseas eliminar a <strong>{username}</strong>?
            <br />
            <span className="text-red-600 text-sm mt-2 block">
              Esta acción no se puede deshacer.
            </span>
          </AlertDialogDescription>
        </AlertDialogHeader>

        {error && (
          <Alert variant="destructive">
            <AlertCircle className="w-4 h-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <div className="flex gap-2 justify-end">
          <AlertDialogCancel disabled={isLoading}>Cancelar</AlertDialogCancel>
          <AlertDialogAction
            onClick={(e) => {
              // Evitamos el cierre automático de Radix para controlarlo nosotros:
              // el diálogo solo se cierra si el borrado tiene éxito (handleConfirm).
              e.preventDefault();
              handleConfirm();
            }}
            disabled={isLoading}
            className="bg-red-600 hover:bg-red-700"
          >
            {isLoading ? 'Eliminando...' : 'Eliminar usuario'}
          </AlertDialogAction>
        </div>
      </AlertDialogContent>
    </AlertDialog>
  );
}
