/**
 * Servicio de API para gestión de usuarios (Admin)
 * Consume los endpoints de administración del servicio de autenticación
 */

interface UserData {
  username: string;
  admin: boolean;
  audit: boolean;
  created_at?: string;
  blocked?: boolean;
}

interface CreateUserPayload {
  username: string;
  password: string;
  admin: boolean;
  audit: boolean;
}

interface UpdateRolePayload {
  admin: boolean;
  audit: boolean;
}

interface UpdatePasswordPayload {
  new_password: string;
}

/** Un intento de inicio de sesión fallido registrado para un usuario. */
export interface FailedLoginAttempt {
  ip_address: string | null;
  user_agent?: string | null;
  timestamp: string | null;
}

/** Información de bloqueo de un usuario (para el diálogo de desbloqueo). */
export interface UserBlockInfo {
  username: string;
  blocked: boolean;
  /** Número de veces que el usuario ha sido bloqueado por el mismo motivo. */
  block_count: number;
  /** Intentos de inicio de sesión fallidos con sus fechas, de más a menos reciente. */
  failed_attempts: FailedLoginAttempt[];
  /** Datos del bloqueo activo actual, si lo hay. */
  current_block: {
    ip_address: string | null;
    blocked_at: string | null;
    reason: string | null;
  } | null;
}

const API_GATEWAY_URL = import.meta.env.VITE_API_GATEWAY_URL || 'http://localhost:3000';

const isValidId = (id: string | null): boolean => {
  if (!id) return false;
  return /^[a-zA-Z0-9\-_]+$/.test(id);
};

/**
 * Construye las cabeceras para las peticiones de administración, incluyendo el
 * x-session-id (y x-user-id) para que el backend pueda registrar la acción con
 * trazabilidad total (quién la realiza y en qué sesión).
 */
function buildAdminHeaders(token: string): Record<string, string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`,
  };
  const sessionId = isValidId(localStorage.getItem('session_id')) ? localStorage.getItem('session_id') : null;
  if (sessionId) headers['x-session-id'] = sessionId;
  const userId = isValidId(localStorage.getItem('user_id')) ? localStorage.getItem('user_id') : null;
  if (userId) headers['x-user-id'] = userId;
  return headers;
}

/**
 * Obtiene la lista de todos los usuarios
 */
export async function getUsers(token: string): Promise<UserData[]> {
  const response = await fetch(`${API_GATEWAY_URL}/api/admin/users`, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`
    }
  });

  if (!response.ok) {
    const data = await response.json();
    throw new Error(data.detail || 'Error al obtener usuarios');
  }

  return response.json();
}

/**
 * Crea un nuevo usuario
 */
export async function createUser(token: string, userData: CreateUserPayload): Promise<UserData> {
  const response = await fetch(`${API_GATEWAY_URL}/api/admin/users`, {
    method: 'POST',
    headers: buildAdminHeaders(token),
    body: JSON.stringify(userData)
  });

  if (!response.ok) {
    const data = await response.json();
    throw new Error(data.detail || 'Error al crear usuario');
  }

  const result = await response.json();
  return result.user;
}

/**
 * Actualiza el rol de un usuario
 */
export async function updateUserRole(
  token: string,
  username: string,
  roles: UpdateRolePayload
): Promise<UserData> {
  const response = await fetch(`${API_GATEWAY_URL}/api/admin/users/${username}/role`, {
    method: 'PUT',
    headers: buildAdminHeaders(token),
    body: JSON.stringify(roles)
  });

  if (!response.ok) {
    const data = await response.json();
    throw new Error(data.detail || 'Error al actualizar rol');
  }

  const result = await response.json();
  return result.user;
}

/**
 * Actualiza la contraseña de un usuario
 */
export async function updateUserPassword(
  token: string,
  username: string,
  newPassword: UpdatePasswordPayload
): Promise<void> {
  const response = await fetch(`${API_GATEWAY_URL}/api/admin/users/${username}/password`, {
    method: 'PUT',
    headers: buildAdminHeaders(token),
    body: JSON.stringify(newPassword)
  });

  if (!response.ok) {
    const data = await response.json();
    throw new Error(data.detail || 'Error al actualizar contraseña');
  }
}

/**
 * Elimina un usuario
 */
export async function deleteUser(token: string, username: string): Promise<void> {
  const response = await fetch(`${API_GATEWAY_URL}/api/admin/users/${username}`, {
    method: 'DELETE',
    headers: buildAdminHeaders(token)
  });

  if (!response.ok) {
    const data = await response.json();
    throw new Error(data.detail || 'Error al eliminar usuario');
  }
}

/**
 * Obtiene la información de bloqueo de un usuario: intentos de inicio de sesión
 * fallidos con sus fechas y el número de veces que ha sido bloqueado.
 */
export async function getUserBlockInfo(token: string, username: string): Promise<UserBlockInfo> {
  const response = await fetch(`${API_GATEWAY_URL}/api/admin/users/${username}/block-info`, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`
    }
  });

  if (!response.ok) {
    const data = await response.json();
    throw new Error(data.detail || 'Error al obtener la información de bloqueo');
  }

  return response.json();
}

/**
 * Desbloquea a un usuario bloqueado por intentos fallidos de inicio de sesión.
 */
export async function unblockUser(token: string, username: string): Promise<void> {
  const response = await fetch(`${API_GATEWAY_URL}/api/admin/users/${username}/unblock`, {
    method: 'POST',
    headers: buildAdminHeaders(token)
  });

  if (!response.ok) {
    const data = await response.json();
    throw new Error(data.detail || 'Error al desbloquear usuario');
  }
}
