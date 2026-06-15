import { useState, useMemo, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  Users,
  Edit2,
  Key,
  Trash2,
  Search,
  X,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Lock,
  ShieldCheck,
  RefreshCw,
} from 'lucide-react';
import { Button } from './ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { Input } from './ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from './ui/select';
import { sanitizeUserInput, MAX_USER_INPUT_LENGTH } from '../utils/input';

interface User {
  username: string;
  admin: boolean;
  audit: boolean;
  created_at?: string;
  blocked?: boolean;
}

interface UsersTableProps {
  users: User[];
  isLoading: boolean;
  onEditRoles: (user: User) => void;
  onChangePassword: (username: string) => void;
  onDelete: (username: string) => void;
  onUnblock: (username: string) => void;
  onRefresh: () => void;
  currentUsername: string;
}

const PAGE_SIZE_OPTIONS = [5, 10, 20, 50];

const getUserRole = (user: User): 'admin' | 'audit' | 'user' =>
  user.admin ? 'admin' : user.audit ? 'audit' : 'user';

export function UsersTable({
  users,
  isLoading,
  onEditRoles,
  onChangePassword,
  onDelete,
  onUnblock,
  onRefresh,
  currentUsername
}: UsersTableProps) {
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState<string>('all');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [pageInput, setPageInput] = useState('1');

  // Filtrado por nombre de usuario, por rol y por estado de bloqueo
  const filteredUsers = useMemo(() => {
    let result = [...users];

    if (search.trim()) {
      const term = search.toLowerCase().trim();
      result = result.filter((u) => u.username.toLowerCase().includes(term));
    }

    if (roleFilter !== 'all') {
      result = result.filter((u) => getUserRole(u) === roleFilter);
    }

    if (statusFilter === 'blocked') {
      result = result.filter((u) => u.blocked);
    } else if (statusFilter === 'active') {
      result = result.filter((u) => !u.blocked);
    }

    return result;
  }, [users, search, roleFilter, statusFilter]);

  const totalPages = Math.max(1, Math.ceil(filteredUsers.length / pageSize));

  // Volver a la primera página cuando cambian los filtros o el tamaño de página
  useEffect(() => {
    setPage(1);
  }, [search, roleFilter, statusFilter, pageSize]);

  // Mantener la página dentro de los límites válidos
  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [page, totalPages]);

  // Sincronizar el input manual de página con la página actual
  useEffect(() => {
    setPageInput(String(page));
  }, [page]);

  const paginatedUsers = useMemo(() => {
    const start = (page - 1) * pageSize;
    return filteredUsers.slice(start, start + pageSize);
  }, [filteredUsers, page, pageSize]);

  const commitPageInput = () => {
    const value = Number.parseInt(pageInput, 10);
    if (Number.isNaN(value)) {
      setPageInput(String(page));
      return;
    }
    const clamped = Math.min(Math.max(1, value), totalPages);
    setPage(clamped);
    setPageInput(String(clamped));
  };

  const rangeStart = filteredUsers.length === 0 ? 0 : (page - 1) * pageSize + 1;
  const rangeEnd = Math.min(page * pageSize, filteredUsers.length);

  // Estado de carga: círculo de carga mientras se traen los usuarios
  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1.5">
              <CardTitle className="flex items-center gap-2">
                <Users className="w-5 h-5" />
                Usuarios
              </CardTitle>
              <CardDescription>Gestión de usuarios del sistema</CardDescription>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={onRefresh}
              disabled={isLoading}
              className="gap-2 shrink-0"
              aria-label="Actualizar lista de usuarios"
            >
              <RefreshCw className="w-4 h-4 animate-spin" />
              Actualizar
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center gap-4 py-16">
            <div className="h-10 w-10 animate-spin rounded-full border-2 border-gray-200 border-t-blue-600" />
            <p className="text-sm text-gray-500">Cargando usuarios...</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-1.5">
            <CardTitle className="flex items-center gap-2">
              <Users className="w-5 h-5" />
              Usuarios ({filteredUsers.length})
            </CardTitle>
            <CardDescription>Gestión de usuarios del sistema</CardDescription>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={onRefresh}
            disabled={isLoading}
            className="gap-2 shrink-0"
            aria-label="Actualizar lista de usuarios"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
            Actualizar
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Controles: búsqueda y filtrado (estilo tabla de auditoría) */}
        <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between pb-4 border-b">
          <div className="flex flex-col sm:flex-row gap-4 flex-1 w-full">
            {/* Buscador por nombre de usuario */}
            <div className="w-full sm:w-64 relative">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400" />
                <Input
                  type="text"
                  placeholder="Buscar usuario"
                  value={search}
                  onChange={(e) => setSearch(sanitizeUserInput(e.target.value))}
                  className="pl-10 pr-8"
                  maxLength={MAX_USER_INPUT_LENGTH}
                />
                {search && (
                  <button
                    onClick={() => setSearch('')}
                    className="absolute right-3 top-1/2 transform -translate-y-1/2 text-gray-400 hover:text-gray-600"
                  >
                    <X className="h-4 w-4" />
                  </button>
                )}
              </div>
            </div>

            {/* Filtro por rol */}
            <div className="w-full sm:w-48">
              <Select value={roleFilter} onValueChange={setRoleFilter}>
                <SelectTrigger>
                  <SelectValue placeholder="Filtrar por rol..." />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Todos los roles</SelectItem>
                  <SelectItem value="admin">Administrador</SelectItem>
                  <SelectItem value="audit">Auditor</SelectItem>
                  <SelectItem value="user">Usuario</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Filtro por estado de bloqueo */}
            <div className="w-full sm:w-48">
              <Select value={statusFilter} onValueChange={setStatusFilter}>
                <SelectTrigger>
                  <SelectValue placeholder="Filtrar por estado..." />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Todos los estados</SelectItem>
                  <SelectItem value="blocked">Bloqueados</SelectItem>
                  <SelectItem value="active">No bloqueados</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>

        {/* Tabla de usuarios */}
        {filteredUsers.length === 0 ? (
          <div className="text-center py-12 text-gray-500">
            {users.length === 0
              ? 'No hay usuarios registrados'
              : 'No se encontraron usuarios con esos criterios'}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="text-left py-3 px-4 font-medium text-gray-700">Usuario</th>
                  <th className="text-left py-3 px-4 font-medium text-gray-700">Roles</th>
                  <th className="text-left py-3 px-4 font-medium text-gray-700">Creado</th>
                  <th className="text-right py-3 px-4 font-medium text-gray-700">Acciones</th>
                </tr>
              </thead>
              {/* La key fuerza el re-montaje al cambiar de página/filtro para
                  reproducir la animación de desvanecimiento de arriba a abajo */}
              <tbody key={`${page}-${roleFilter}-${statusFilter}-${search}`}>
                {paginatedUsers.map((user, idx) => (
                  <motion.tr
                    key={user.username}
                    initial={{ opacity: 0, y: -8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{
                      duration: 0.3,
                      delay: Math.min(idx * 0.04, 0.4),
                      ease: 'easeOut',
                    }}
                    className={
                      user.blocked
                        ? 'border-b border-red-200 bg-red-50 hover:bg-red-100'
                        : 'border-b border-gray-100 hover:bg-gray-50'
                    }
                  >
                    <td className="py-3 px-4">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-gray-900">{user.username}</span>
                        {user.blocked && (
                          <Badge className="bg-red-600 text-white hover:bg-red-600 gap-1">
                            <Lock className="w-3 h-3" />
                            Bloqueado
                          </Badge>
                        )}
                      </div>
                      {user.username === currentUsername && (
                        <div className="text-xs text-blue-600 mt-1">Tu cuenta</div>
                      )}
                    </td>
                    <td className="py-3 px-4">
                      <div className="flex gap-2">
                        {user.admin && (
                          <Badge className="bg-red-100 text-red-700 hover:bg-red-100">Admin</Badge>
                        )}
                        {user.audit && (
                          <Badge className="bg-blue-100 text-blue-700 hover:bg-blue-100">Auditor</Badge>
                        )}
                        {!user.admin && !user.audit && (
                          <Badge className="bg-gray-100 text-gray-700 hover:bg-gray-100">Usuario</Badge>
                        )}
                      </div>
                    </td>
                    <td className="py-3 px-4 text-gray-600">
                      {user.created_at
                        ? new Date(user.created_at).toLocaleString('es-ES', {
                            year: 'numeric',
                            month: '2-digit',
                            day: '2-digit',
                            hour: '2-digit',
                            minute: '2-digit'
                          })
                        : 'N/A'}
                    </td>
                    <td className="py-3 px-4">
                      <div className="flex gap-2 justify-end">
                        {user.blocked && (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => onUnblock(user.username)}
                            className="gap-1 text-xs text-green-700 border-green-300 hover:text-green-800 hover:bg-green-50"
                          >
                            <ShieldCheck className="w-3 h-3" />
                            Desbloquear
                          </Button>
                        )}
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => onEditRoles(user)}
                          className="gap-1 text-xs"
                        >
                          <Edit2 className="w-3 h-3" />
                          Roles
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => onChangePassword(user.username)}
                          className="gap-1 text-xs"
                        >
                          <Key className="w-3 h-3" />
                          Contraseña
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => onDelete(user.username)}
                          disabled={user.username === currentUsername}
                          className="gap-1 text-xs text-red-600 hover:text-red-700 hover:bg-red-50"
                        >
                          <Trash2 className="w-3 h-3" />
                          Eliminar
                        </Button>
                      </div>
                    </td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Controles de paginación */}
        {filteredUsers.length > 0 && (
          <div className="flex flex-col sm:flex-row items-center justify-between gap-4 pt-4 border-t">
            {/* Elementos por página */}
            <div className="flex items-center gap-2 text-sm text-gray-600">
              <span>Filas por página</span>
              <Select value={String(pageSize)} onValueChange={(v) => setPageSize(Number(v))}>
                <SelectTrigger className="w-20">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PAGE_SIZE_OPTIONS.map((n) => (
                    <SelectItem key={n} value={String(n)}>
                      {n}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Rango y navegación */}
            <div className="flex flex-col sm:flex-row items-center gap-3">
              <span className="text-sm text-gray-600">
                {rangeStart}–{rangeEnd} de {filteredUsers.length}
              </span>

              <div className="flex items-center gap-1">
                <Button
                  variant="outline"
                  size="icon"
                  className="h-8 w-8"
                  onClick={() => setPage(1)}
                  disabled={page === 1}
                  aria-label="Primera página"
                >
                  <ChevronsLeft className="h-4 w-4" />
                </Button>
                <Button
                  variant="outline"
                  size="icon"
                  className="h-8 w-8"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  aria-label="Página anterior"
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>

                <div className="flex items-center gap-1 px-1">
                  <Input
                    type="number"
                    min={1}
                    max={totalPages}
                    value={pageInput}
                    onChange={(e) => setPageInput(e.target.value)}
                    onBlur={commitPageInput}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        commitPageInput();
                        (e.target as HTMLInputElement).blur();
                      }
                    }}
                    className="h-8 w-14 text-center"
                    aria-label="Número de página"
                  />
                  <span className="text-sm text-gray-600 whitespace-nowrap">/ {totalPages}</span>
                </div>

                <Button
                  variant="outline"
                  size="icon"
                  className="h-8 w-8"
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  aria-label="Página siguiente"
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
                <Button
                  variant="outline"
                  size="icon"
                  className="h-8 w-8"
                  onClick={() => setPage(totalPages)}
                  disabled={page === totalPages}
                  aria-label="Última página"
                >
                  <ChevronsRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
