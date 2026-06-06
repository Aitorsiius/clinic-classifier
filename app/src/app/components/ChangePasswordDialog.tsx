import { useState } from 'react';
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogHeader, AlertDialogTitle } from './ui/alert-dialog';
import { PasswordInput } from './ui/password-input';
import { Label } from './ui/label';
import { Alert, AlertDescription } from './ui/alert';
import { AlertCircle } from 'lucide-react';
import { sanitizeUserInput, MAX_USER_INPUT_LENGTH } from '../utils/input';

interface ChangePasswordDialogProps {
  open: boolean;
  username: string;
  onOpenChange: (open: boolean) => void;
  onConfirm: (username: string, newPassword: string) => Promise<void>;
  isLoading: boolean;
}

export function ChangePasswordDialog({
  open,
  username,
  onOpenChange,
  onConfirm,
  isLoading
}: ChangePasswordDialogProps) {
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const validateForm = (): string | null => {
    if (!newPassword) {
      return 'La nueva contraseña es requerida';
    }
    if (newPassword.length < 6) {
      return 'La contraseña debe tener al menos 6 caracteres';
    }
    if (newPassword !== confirmPassword) {
      return 'Las contraseñas no coinciden';
    }
    return null;
  };

  const isFormValid = validateForm() === null;

  const getPasswordError = (): string | null => {
    if (!newPassword || !confirmPassword) return null;
    if (newPassword !== confirmPassword) {
      return 'Las contraseñas no coinciden';
    }
    return null;
  };

  const handleConfirm = async () => {
    const validationError = validateForm();
    if (validationError) {
      setError(validationError);
      return;
    }

    try {
      setError(null);
      await onConfirm(username, newPassword);
      setSuccess(true);
      setNewPassword('');
      setConfirmPassword('');
      setTimeout(() => {
        setSuccess(false);
        onOpenChange(false);
      }, 2000);
    } catch (err) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Error al cambiar contraseña');
      }
    }
  };

  const handleOpenChange = (newOpen: boolean) => {
    if (!newOpen && !isLoading) {
      setError(null);
      setSuccess(false);
      setNewPassword('');
      setConfirmPassword('');
      onOpenChange(false);
    }
  };

  return (
    <AlertDialog open={open} onOpenChange={handleOpenChange}>
      <AlertDialogContent className="max-w-md">
        <AlertDialogHeader>
          <AlertDialogTitle>Cambiar contraseña</AlertDialogTitle>
          <AlertDialogDescription>
            Cambiar contraseña para el usuario: <strong>{username}</strong>
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className="space-y-4 py-4">
          {success && (
            <Alert className="bg-green-50 border-green-200">
              <AlertCircle className="w-4 h-4 text-green-600" />
              <AlertDescription className="text-green-800">
                ✓ Contraseña actualizada exitosamente
              </AlertDescription>
            </Alert>
          )}

          {error && (
            <Alert variant="destructive">
              <AlertCircle className="w-4 h-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <div className="space-y-2">
            <Label htmlFor="newPassword">Nueva contraseña</Label>
            <PasswordInput
              id="newPassword"
              placeholder="••••••••"
              value={newPassword}
              onChange={(e: any) => setNewPassword(sanitizeUserInput(e.target.value))}
              disabled={isLoading}
              minLength={6}
              maxLength={MAX_USER_INPUT_LENGTH}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="confirmPassword">Confirmar contraseña</Label>
            <PasswordInput
              id="confirmPassword"
              placeholder="••••••••"
              value={confirmPassword}
              onChange={(e: any) => setConfirmPassword(sanitizeUserInput(e.target.value))}
              disabled={isLoading}
              minLength={6}
              maxLength={MAX_USER_INPUT_LENGTH}
              className={getPasswordError() ? 'border-red-500' : ''}
            />
            {getPasswordError() && (
              <p className="text-sm text-red-600">{getPasswordError()}</p>
            )}
          </div>
        </div>

        <div className="flex gap-2 justify-end">
          <AlertDialogCancel disabled={isLoading}>Cancelar</AlertDialogCancel>
          <AlertDialogAction
            onClick={handleConfirm}
            disabled={isLoading || !isFormValid || success}
            className={`${!isFormValid ? 'opacity-50 cursor-not-allowed' : ''} bg-blue-600 hover:bg-blue-700`}
          >
            {isLoading ? 'Cambiando...' : 'Cambiar contraseña'}
          </AlertDialogAction>
        </div>
      </AlertDialogContent>
    </AlertDialog>
  );
}
