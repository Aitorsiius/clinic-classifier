import { useState } from 'react';
import { AlertDialog, AlertDialogContent, AlertDialogDescription, AlertDialogHeader, AlertDialogTitle } from './ui/alert-dialog';
import { Input } from './ui/input';
import { PasswordInput } from './ui/password-input';
import { Label } from './ui/label';
import { RadioGroup, RadioGroupItem } from './ui/radio-group';
import { Button } from './ui/button';
import { Alert, AlertDescription } from './ui/alert';
import { AlertCircle } from 'lucide-react';
import { sanitizeUserInput, MAX_USER_INPUT_LENGTH } from '../utils/input';

interface CreateUserDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (username: string, password: string, admin: boolean, audit: boolean) => Promise<void>;
  isLoading: boolean;
}

export function CreateUserDialog({
  open,
  onOpenChange,
  onConfirm,
  isLoading
}: Readonly<CreateUserDialogProps>) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [admin, setAdmin] = useState(false);
  const [audit, setAudit] = useState(false);
  const [user, setUser] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const validateForm = (): string | null => {
    if (!username.trim()) {
      return 'El nombre de usuario es requerido';
    }
    if (username.length < 3) {
      return 'El nombre de usuario debe tener al menos 3 caracteres';
    }
    if (!password) {
      return 'La contraseña es requerida';
    }
    if (password.length < 6) {
      return 'La contraseña debe tener al menos 6 caracteres';
    }
    if (password !== confirmPassword) {
      return 'Las contraseñas no coinciden';
    }
    const rolesSelected = [admin, audit, user].filter(Boolean).length;
    if (rolesSelected === 0) {
      return 'El usuario debe tener un rol';
    }
    if (rolesSelected > 1) {
      return 'El usuario puede tener solo un rol';
    }
    return null;
  };

  const validationError = validateForm();
  const isFormValid = validationError === null;

  // Rol actualmente seleccionado, derivado de los flags booleanos del formulario.
  const getSelectedRole = () => {
    if (admin) return 'admin';
    if (audit) return 'audit';
    if (user) return 'user';
    return '';
  };
  const selectedRole = getSelectedRole();

  const handleRoleChange = (role: string) => {
    // Selección exclusiva: al elegir un rol se desmarcan automáticamente los demás.
    setAdmin(role === 'admin');
    setAudit(role === 'audit');
    setUser(role === 'user');
  };

  const getPasswordError = (): string | null => {
    if (!password || !confirmPassword) return null;
    if (password !== confirmPassword) {
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
      await onConfirm(username.trim(), password, admin, audit);
      // Reset del formulario y cierre directo del diálogo tras crear el usuario
      setUsername('');
      setPassword('');
      setConfirmPassword('');
      setAdmin(false);
      setAudit(false);
      setUser(false);
      onOpenChange(false);
    } catch (err) {
      // Si hay error, mostrar el mensaje y mantener el diálogo abierto
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Error al crear usuario');
      }
    }
  };

  const handleOpenChange = (newOpen: boolean) => {
    // Solo permitir cerrar si no está cargando Y no hay error
    if (!newOpen && !isLoading && !error) {
      setError(null);
      setUsername('');
      setPassword('');
      setConfirmPassword('');
      setAdmin(false);
      setAudit(false);
      setUser(false);
      onOpenChange(false);
    }
  };

  return (
    <AlertDialog open={open} onOpenChange={handleOpenChange}>
      <AlertDialogContent className="max-w-md">
        <AlertDialogHeader>
          <AlertDialogTitle>Crear nuevo usuario</AlertDialogTitle>
          <AlertDialogDescription>
            Completa los datos para crear un nuevo usuario en el sistema
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className="space-y-4 py-4">
          {error && (
            <Alert variant="destructive">
              <AlertCircle className="w-4 h-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <div className="space-y-2">
            <Label htmlFor="username">Nombre de usuario</Label>
            <Input
              id="username"
              placeholder="juan_perez"
              value={username}
              onChange={(e) => setUsername(sanitizeUserInput(e.target.value))}
              disabled={isLoading}
              minLength={3}
              maxLength={MAX_USER_INPUT_LENGTH}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="password">Contraseña</Label>
            <PasswordInput
              id="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(sanitizeUserInput(e.target.value))}
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
              onChange={(e) => setConfirmPassword(sanitizeUserInput(e.target.value))}
              disabled={isLoading}
              minLength={6}
              maxLength={MAX_USER_INPUT_LENGTH}
              className={getPasswordError() ? 'border-red-500' : ''}
            />
            {getPasswordError() && (
              <p className="text-sm text-red-600">{getPasswordError()}</p>
            )}
          </div>

          <div className="space-y-3 pt-2">
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
                <RadioGroupItem value="user" id="user" />
                <Label htmlFor="user" className="font-normal cursor-pointer">
                  Usuario - Acceso básico a búsquedas
                </Label>
              </div>
            </RadioGroup>
          </div>
        </div>

        <div className="flex gap-2 justify-end">
          <Button
            variant="outline"
            onClick={() => {
              if (!isLoading) {
                setError(null);
                setUsername('');
                setPassword('');
                setConfirmPassword('');
                setAdmin(false);
                setAudit(false);
                setUser(false);
                onOpenChange(false);
              }
            }}
            disabled={isLoading}
          >
            Cancelar
          </Button>
          <Button
            onClick={handleConfirm}
            disabled={isLoading || !isFormValid}
            className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isLoading ? 'Creando...' : 'Crear usuario'}
          </Button>
        </div>
      </AlertDialogContent>
    </AlertDialog>
  );
}
