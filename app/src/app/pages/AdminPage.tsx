import { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import { useSession } from '../context/SessionContext';
import { useNavigate } from 'react-router-dom';
import { Header } from '../components/Header';
import { Button } from '../components/ui/button';
import { Alert, AlertDescription } from '../components/ui/alert';
import { AlertCircle, Plus } from 'lucide-react';
import { UsersTable } from '../components/UsersTable';
import { CreateUserDialog } from '../components/CreateUserDialog';
import { ChangePasswordDialog } from '../components/ChangePasswordDialog';
import { EditRolesDialog } from '../components/EditRolesDialog';
import { DeleteUserDialog } from '../components/DeleteUserDialog';
import { UnblockUserDialog } from '../components/UnblockUserDialog';
import {
  getUsers,
  createUser,
  updateUserPassword,
  updateUserRole,
  deleteUser,
  getUserBlockInfo,
  unblockUser,
  type UserBlockInfo,
} from '../services/adminService';

interface User {
  username: string;
  admin: boolean;
  audit: boolean;
  created_at?: string;
  blocked?: boolean;
}

export default function AdminPage() {
  const navigate = useNavigate();
  const { isAuthenticated, userData, token } = useAuth();
  const { incrementStat } = useSession();

  // State para usuarios
  const [users, setUsers] = useState<User[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // State para diálogos
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [changePasswordDialogOpen, setChangePasswordDialogOpen] = useState(false);
  const [editRolesDialogOpen, setEditRolesDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [unblockDialogOpen, setUnblockDialogOpen] = useState(false);

  // State para operaciones
  const [selectedUsername, setSelectedUsername] = useState<string | null>(null);
  const [selectedUser, setSelectedUser] = useState<User | null>(null);
  const [operationLoading, setOperationLoading] = useState(false);
  const [operationError, setOperationError] = useState<string | null>(null);

  // State para el desbloqueo de usuarios
  const [selectedBlockInfo, setSelectedBlockInfo] = useState<UserBlockInfo | null>(null);
  const [blockInfoLoading, setBlockInfoLoading] = useState(false);

  useEffect(() => {
    const clearErrors = () => {
      setError(null);
      setOperationError(null);
    };
    globalThis.addEventListener('auth:logout', clearErrors);
    return () => globalThis.removeEventListener('auth:logout', clearErrors);
  }, []);

  // Verificar que es admin
  useEffect(() => {
    if (!isAuthenticated || !userData?.admin) {
      navigate('/search');
    }
  }, [isAuthenticated, userData, navigate]);

  // Cargar usuarios
  useEffect(() => {
    if (isAuthenticated && token) {
      loadUsers();
    }
  }, [isAuthenticated, token]);

  const loadUsers = async () => {
    try {
      setError(null);
      setIsLoading(true);
      if (!token) {
        throw new Error('No hay token de autenticación disponible');
      }
      const data = await getUsers(token);
      setUsers(data);
    } catch (err) {
      let errorMessage = 'Error al cargar usuarios';
      if (err instanceof Error) {
        errorMessage = err.message;
      }
      setError(errorMessage);
      console.error('Error loading users:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleCreateUser = async (
    username: string,
    password: string,
    admin: boolean,
    audit: boolean
  ) => {
    try {
      setOperationError(null);
      setOperationLoading(true);
      if (!token) {
        throw new Error('No hay token de autenticación disponible');
      }
      await createUser(token, {
        username,
        password,
        admin,
        audit
      });
      // Contabilizar la creación de usuario en las estadísticas de la sesión
      incrementStat('usersCreated');
      // Recargar usuarios. El diálogo se cierra solo tras mostrar el mensaje
      // de éxito durante unos segundos (gestionado por el propio diálogo).
      await loadUsers();
    } catch (err) {
      let errorMessage = 'Error al crear usuario';
      if (err instanceof Error) {
        errorMessage = err.message;
      }
      setOperationError(errorMessage);
      throw err;
    } finally {
      setOperationLoading(false);
    }
  };

  const handleChangePassword = async (username: string, newPassword: string) => {
    try {
      setOperationError(null);
      setOperationLoading(true);
      if (!token) {
        throw new Error('No hay token de autenticación disponible');
      }
      await updateUserPassword(token, username, { new_password: newPassword });
      // Contabilizar el cambio de contraseña en las estadísticas de la sesión
      incrementStat('passwordsChanged');
      // El diálogo permanece abierto mostrando el mensaje de éxito y se cierra
      // solo pasados unos segundos (gestionado por el propio diálogo).
      setError(null);
    } catch (err) {
      let errorMessage = 'Error al cambiar contraseña';
      if (err instanceof Error) {
        errorMessage = err.message;
      }
      setOperationError(errorMessage);
      throw err;
    } finally {
      setOperationLoading(false);
    }
  };

  const handleEditRoles = async (username: string, admin: boolean, audit: boolean) => {
    try {
      setOperationError(null);
      setOperationLoading(true);
      if (!token) {
        throw new Error('No hay token de autenticación disponible');
      }
      await updateUserRole(token, username, { admin, audit });
      // Contabilizar el cambio de rol en las estadísticas de la sesión
      incrementStat('roleChanges');
      // Recargar usuarios. El diálogo se mantiene abierto mostrando el mensaje
      // de éxito y se cierra solo pasados unos segundos.
      await loadUsers();
    } catch (err) {
      let errorMessage = 'Error al actualizar roles';
      if (err instanceof Error) {
        errorMessage = err.message;
      }
      setOperationError(errorMessage);
      throw err;
    } finally {
      setOperationLoading(false);
    }
  };

  const handleDeleteUser = async (username: string) => {
    try {
      setOperationError(null);
      setOperationLoading(true);
      if (!token) {
        throw new Error('No hay token de autenticación disponible');
      }
      await deleteUser(token, username);
      // Contabilizar la eliminación de usuario en las estadísticas de la sesión
      incrementStat('usersDeleted');
      // Recargar usuarios. El diálogo se mantiene abierto mostrando el mensaje
      // de éxito y se cierra solo pasados unos segundos.
      await loadUsers();
    } catch (err) {
      let errorMessage = 'Error al eliminar usuario';
      if (err instanceof Error) {
        errorMessage = err.message;
      }
      setOperationError(errorMessage);
      throw err;
    } finally {
      setOperationLoading(false);
    }
  };

  const handleOpenChangePassword = (username: string) => {
    setOperationError(null);
    setSelectedUsername(username);
    setChangePasswordDialogOpen(true);
  };

  const handleOpenEditRoles = (user: User) => {
    setOperationError(null);
    setSelectedUser(user);
    setEditRolesDialogOpen(true);
  };

  const handleOpenDelete = (username: string) => {
    setOperationError(null);
    setSelectedUsername(username);
    setDeleteDialogOpen(true);
  };

  // Abre el diálogo de desbloqueo y carga la información de bloqueo del usuario
  // (intentos fallidos con sus fechas y nº de veces bloqueado).
  const handleOpenUnblock = async (username: string) => {
    setOperationError(null);
    setSelectedUsername(username);
    setSelectedBlockInfo(null);
    setUnblockDialogOpen(true);

    if (!token) {
      setOperationError('No hay token de autenticación disponible');
      return;
    }

    try {
      setBlockInfoLoading(true);
      const info = await getUserBlockInfo(token, username);
      setSelectedBlockInfo(info);
    } catch (err) {
      let errorMessage = 'Error al cargar la información de bloqueo';
      if (err instanceof Error) {
        errorMessage = err.message;
      }
      setOperationError(errorMessage);
      console.error('Error loading block info:', err);
    } finally {
      setBlockInfoLoading(false);
    }
  };

  const handleUnblockUser = async (username: string) => {
    try {
      setOperationError(null);
      setOperationLoading(true);
      if (!token) {
        throw new Error('No hay token de autenticación disponible');
      }
      await unblockUser(token, username);
      incrementStat('usersUnblocked');
      // Recargar usuarios para reflejar que ya no está bloqueado.
      await loadUsers();
    } catch (err) {
      let errorMessage = 'Error al desbloquear usuario';
      if (err instanceof Error) {
        errorMessage = err.message;
      }
      setOperationError(errorMessage);
      throw err;
    } finally {
      setOperationLoading(false);
    }
  };

  if (!isAuthenticated || !userData?.admin) {
    return null;
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <Header />

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Encabezado */}
        <div className="mb-8">
          <h2 className="text-3xl font-bold text-gray-900">Administración</h2>
          <p className="text-gray-600 mt-2">Gestiona los usuarios de la aplicación</p>
        </div>

        {/* Errores globales */}
        {error && (
          <Alert variant="destructive" className="mb-6">
            <AlertCircle className="w-4 h-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {/* Botón para crear usuario */}
        <div className="mb-6 flex gap-3">
          <Button
            onClick={() => setCreateDialogOpen(true)}
            variant="brand"
            className="gap-2"
          >
            <Plus className="w-4 h-4" />
            Crear nuevo usuario
          </Button>
        </div>

        {/* Tabla de usuarios */}
        <UsersTable
          users={users}
          isLoading={isLoading}
          onEditRoles={handleOpenEditRoles}
          onChangePassword={handleOpenChangePassword}
          onDelete={handleOpenDelete}
          onUnblock={handleOpenUnblock}
          onRefresh={loadUsers}
          currentUsername={userData?.username || ''}
        />
      </main>

      {/* Diálogos */}
      <CreateUserDialog
        open={createDialogOpen}
        onOpenChange={setCreateDialogOpen}
        onConfirm={handleCreateUser}
        isLoading={operationLoading}
      />

      <ChangePasswordDialog
        open={changePasswordDialogOpen}
        username={selectedUsername || ''}
        onOpenChange={setChangePasswordDialogOpen}
        onConfirm={handleChangePassword}
        isLoading={operationLoading}
      />

      <EditRolesDialog
        open={editRolesDialogOpen}
        user={selectedUser}
        onOpenChange={setEditRolesDialogOpen}
        onConfirm={handleEditRoles}
        isLoading={operationLoading}
      />

      <DeleteUserDialog
        open={deleteDialogOpen}
        username={selectedUsername || ''}
        onOpenChange={setDeleteDialogOpen}
        onConfirm={handleDeleteUser}
        isLoading={operationLoading}
        error={operationError}
      />

      <UnblockUserDialog
        open={unblockDialogOpen}
        username={selectedUsername || ''}
        blockInfo={selectedBlockInfo}
        isLoadingInfo={blockInfoLoading}
        isUnblocking={operationLoading}
        error={operationError}
        onOpenChange={setUnblockDialogOpen}
        onConfirm={handleUnblockUser}
      />
    </div>
  );
}
