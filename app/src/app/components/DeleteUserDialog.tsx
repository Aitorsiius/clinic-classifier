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
}: Readonly<DeleteUserDialogProps>) {
  const handleConfirm = () => {
    // Solo cerramos el diálogo si el borrado tiene éxito. Si falla, el padre
    // ya muestra el error (prop `error`) y relanza, así que mantenemos el
    // diálogo abierto sin acción adicional aquí.
    onConfirm(username)
      .then(() => onOpenChange(false))
      .catch(() => {
        // Error ya gestionado por el padre.
      });
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
