import { useState, useEffect } from 'react';
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogHeader, AlertDialogTitle } from './ui/alert-dialog';
import { RadioGroup, RadioGroupItem } from './ui/radio-group';
import { Label } from './ui/label';
import { Alert, AlertDescription } from './ui/alert';
import { AlertCircle } from 'lucide-react';

interface EditRolesDialogProps {
  open: boolean;
  user: {
    username: string;
    admin: boolean;
    audit: boolean;
  } | null;
  onOpenChange: (open: boolean) => void;
  onConfirm: (username: string, admin: boolean, audit: boolean) => Promise<void>;
  isLoading: boolean;
}

export function EditRolesDialog({
  open,
  user,
  onOpenChange,
  onConfirm,
  isLoading
}: EditRolesDialogProps) {
  const [admin, setAdmin] = useState(user?.admin || false);
  const [audit, setAudit] = useState(user?.audit || false);
  const [user_role, setUserRole] = useState(!user?.admin && !user?.audit);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  // Sincronizar state cuando cambia el usuario
  useEffect(() => {
    if (user) {
      setAdmin(user.admin);
      setAudit(user.audit);
      setUserRole(!user.admin && !user.audit);
      setError(null);
      setSuccess(false);
    }
  }, [user, open]);

  const validateForm = (): string | null => {
    const rolesSelected = [admin, audit, user_role].filter(Boolean).length;
    if (rolesSelected === 0) {
      return 'El usuario debe tener un rol';
    }
    if (rolesSelected > 1) {
      return 'El usuario puede tener solo un rol';
    }
    return null;
  };

  const isFormValid = validateForm() === null;
  const hasChanges = user && (admin !== user.admin || audit !== user.audit || (!user.admin && !user.audit) !== user_role);

  // Rol actualmente seleccionado, derivado de los flags booleanos del formulario.
  const selectedRole = admin ? 'admin' : audit ? 'audit' : user_role ? 'user' : '';

  const handleRoleChange = (role: string) => {
    // Selección exclusiva: al elegir un rol se desmarcan automáticamente los demás.
    setAdmin(role === 'admin');
    setAudit(role === 'audit');
    setUserRole(role === 'user');
  };

  const handleConfirm = async () => {
    const validationError = validateForm();
    if (validationError) {
      setError(validationError);
      return;
    }

    if (!user) return;

    try {
      setError(null);
      await onConfirm(user.username, admin, audit);
      setSuccess(true);
      setTimeout(() => {
        setSuccess(false);
        onOpenChange(false);
      }, 2000);
    } catch (err) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Error al actualizar roles');
      }
    }
  };

  const handleOpenChange = (newOpen: boolean) => {
    if (!newOpen && !isLoading) {
      setError(null);
      setSuccess(false);
      onOpenChange(false);
    }
  };

  if (!user) return null;

  return (
    <AlertDialog open={open} onOpenChange={handleOpenChange}>
      <AlertDialogContent className="max-w-md">
        <AlertDialogHeader>
          <AlertDialogTitle>Editar roles</AlertDialogTitle>
          <AlertDialogDescription>
            Actualizar roles para el usuario: <strong>{user.username}</strong>
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className="space-y-4 py-4">
          {success && (
            <Alert className="bg-green-50 border-green-200">
              <AlertCircle className="w-4 h-4 text-green-600" />
              <AlertDescription className="text-green-800">
                ✓ Roles actualizados exitosamente
              </AlertDescription>
            </Alert>
          )}

          {error && (
            <Alert variant="destructive">
              <AlertCircle className="w-4 h-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <div className="space-y-3">
            <div className="text-sm font-medium">Rol</div>
            <RadioGroup value={selectedRole} onValueChange={handleRoleChange} disabled={isLoading}>
              <div className="flex items-center space-x-2">
                <RadioGroupItem value="admin" id="admin" />
                <Label htmlFor="admin" className="font-normal cursor-pointer">
                  Administrador - Gestiona usuarios y configuración
                </Label>
              </div>
              <div className="flex items-center space-x-2">
                <RadioGroupItem value="audit" id="audit" />
                <Label htmlFor="audit" className="font-normal cursor-pointer">
                  Auditor - Acceso a historiales y reportes
                </Label>
              </div>
              <div className="flex items-center space-x-2">
                <RadioGroupItem value="user" id="user_role" />
                <Label htmlFor="user_role" className="font-normal cursor-pointer">
                  Usuario - Acceso básico a búsquedas
                </Label>
              </div>
            </RadioGroup>
          </div>
        </div>

        <div className="flex gap-2 justify-end">
          <AlertDialogCancel disabled={isLoading}>Cancelar</AlertDialogCancel>
          <AlertDialogAction
            onClick={handleConfirm}
            disabled={isLoading || !isFormValid || !hasChanges || success}
            className={`${!hasChanges || !isFormValid ? 'opacity-50 cursor-not-allowed' : ''} bg-blue-600 hover:bg-blue-700`}
          >
            {isLoading ? 'Actualizando...' : 'Actualizar roles'}
          </AlertDialogAction>
        </div>
      </AlertDialogContent>
    </AlertDialog>
  );
}
