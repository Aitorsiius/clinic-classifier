/**
 * Servicio de API para gestión de usuarios (Admin)
 * Consume los endpoints de administración del servicio de autenticación
 */

interface UserData {
  username: string;
  admin: boolean;
  audit: boolean;
  created_at?: string;
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

const API_GATEWAY_URL = (import.meta as any).env.VITE_API_GATEWAY_URL || 'http://localhost:3000';

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
  const sessionId = localStorage.getItem('session_id');
  if (sessionId) headers['x-session-id'] = sessionId;
  const userId = localStorage.getItem('user_id');
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
