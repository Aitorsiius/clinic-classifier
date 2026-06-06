import { useEffect } from 'react';
import { LogOut, LogIn, Shield, ClipboardCheck, User } from 'lucide-react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useSession } from '../context/SessionContext';

export function Header() {
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated, username, userData, logout } = useAuth();
  const { auditNotification, setAuditNotification, searchNotification, setSearchNotification } = useSession();

  const handleLogout = async () => {
    // logout() activa el overlay de desvanecimiento y espera a que cubra la
    // pantalla antes de limpiar el estado; navegamos con el overlay visible
    // para que la recolocación de la interfaz no se vea brusca.
    await logout();
    navigate('/search');
  };

  const handleLoginClick = () => {
    navigate('/login');
  };

  const isAuditPage = location.pathname === '/audit';
  const isSearchPage = location.pathname === '/search';

  // Aviso de auditoría: al entrar en /audit se descarta el aviso visual pendiente
  // (el usuario ya está viendo el resultado de la auditoría finalizada).
  // La notificación se activa en AuditPanel cuando el proceso termina y el
  // usuario no está en /audit.
  useEffect(() => {
    if (isAuditPage && auditNotification) {
      setAuditNotification(false);
    }
  }, [isAuditPage, auditNotification, setAuditNotification]);

  // Aviso de clasificación: mismo comportamiento que el de auditoría. La
  // notificación se activa en SearchPage cuando la búsqueda termina y el
  // usuario no está en /search; aquí solo se descarta al entrar en la vista.
  useEffect(() => {
    if (isSearchPage && searchNotification) {
      setSearchNotification(false);
    }
  }, [isSearchPage, searchNotification, setSearchNotification]);

  return (
    <header className="bg-white border-b border-slate-200 shadow-sm">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <div className="flex items-center justify-between">
          <Link to="/search" className="flex items-center gap-3 hover:opacity-80 transition">
            <img 
              src="/chinchilla.png" 
              alt="Chinchilla Logo" 
              className="w-18 h-18 rounded-lg"
            />
            <div>
              <h1 className="text-2xl text-slate-900">
                Clasificador CIE-10 ES
              </h1>
              <p className="text-sm text-slate-600 mt-0.5">
                Sistema de clasificación automática de diagnósticos médicos
              </p>
            </div>
          </Link>

          <div className="flex items-center gap-4">
            {isAuthenticated && (
              <nav className="flex gap-2">
                <Link
                  to="/search"
                  className={`relative px-4 py-2 rounded-lg font-medium transition ${
                    isSearchPage
                      ? 'bg-blue-100 text-blue-700'
                      : 'text-gray-600 hover:bg-gray-100'
                  }`}
                >
                  Clasificar
                  {searchNotification && !isSearchPage && (
                    <span
                      className="absolute -top-1 -right-1 flex h-3 w-3"
                      role="status"
                      aria-label="Resultado de búsqueda disponible"
                      title="Resultado de búsqueda disponible"
                    >
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75"></span>
                      <span className="relative inline-flex h-3 w-3 rounded-full bg-amber-500"></span>
                    </span>
                  )}
                </Link>
                {(userData?.audit || userData?.admin) && (
                  <Link
                    to="/audit"
                    className={`relative px-4 py-2 rounded-lg font-medium transition ${
                      isAuditPage
                        ? 'bg-blue-100 text-blue-700'
                        : 'text-gray-600 hover:bg-gray-100'
                    }`}
                  >
                    Auditar
                    {auditNotification && !isAuditPage && (
                      <span
                        className="absolute -top-1 -right-1 flex h-3 w-3"
                        role="status"
                        aria-label="Auditoría finalizada"
                        title="Auditoría finalizada"
                      >
                        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75"></span>
                        <span className="relative inline-flex h-3 w-3 rounded-full bg-amber-500"></span>
                      </span>
                    )}
                  </Link>
                )}
                {userData?.admin && (
                  <Link
                    to="/admin"
                    className={`px-4 py-2 rounded-lg font-medium transition ${
                      location.pathname === '/admin'
                        ? 'bg-blue-100 text-blue-700'
                        : 'text-gray-600 hover:bg-gray-100'
                    }`}
                  >
                    Administrar
                  </Link>
                )}
              </nav>
            )}

            <div className="border-l border-slate-200 pl-4 flex items-center gap-3">
              {isAuthenticated ? (
                <>
                  {/* Tarjeta de identidad: avatar con inicial + nombre + rol(es) */}
                  <div className="flex items-center gap-2.5 rounded-xl border border-slate-200 bg-slate-50/70 py-1.5 pl-1.5 pr-3">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-blue-600 to-indigo-600 text-sm font-semibold text-white shadow-sm shadow-blue-600/20">
                      {username?.charAt(0).toUpperCase()}
                    </div>
                    <div className="flex flex-col leading-tight">
                      <span className="text-sm font-semibold text-slate-900">{username}</span>
                      <div className="mt-0.5 flex items-center gap-1">
                        {userData?.admin && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-1.5 py-0.5 text-[0.6875rem] font-medium text-red-700 ring-1 ring-inset ring-red-200">
                            <Shield className="h-3 w-3" />
                            Admin
                          </span>
                        )}
                        {userData?.audit && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-1.5 py-0.5 text-[0.6875rem] font-medium text-blue-700 ring-1 ring-inset ring-blue-200">
                            <ClipboardCheck className="h-3 w-3" />
                            Auditor
                          </span>
                        )}
                        {!userData?.admin && !userData?.audit && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-1.5 py-0.5 text-[0.6875rem] font-medium text-slate-600 ring-1 ring-inset ring-slate-200">
                            <User className="h-3 w-3" />
                            Usuario
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                  <button
                    onClick={handleLogout}
                    className="flex items-center gap-2 rounded-xl border border-slate-200 px-3 py-2 text-sm font-medium text-slate-600 transition-all duration-200 hover:border-red-200 hover:bg-red-50 hover:text-red-600"
                    title="Cerrar sesión"
                  >
                    <LogOut className="w-4 h-4" />
                    <span className="hidden md:inline">Cerrar Sesión</span>
                  </button>
                </>
              ) : (
                <button
                  onClick={handleLoginClick}
                  className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 px-4 py-2 text-sm font-medium text-white shadow-lg shadow-blue-600/25 transition-all duration-200 hover:-translate-y-0.5 hover:from-blue-700 hover:to-indigo-700 hover:shadow-xl hover:shadow-blue-600/30 active:translate-y-0 active:scale-[0.98]"
                >
                  <LogIn className="w-4 h-4" />
                  Iniciar Sesión
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}
