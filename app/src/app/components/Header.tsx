import { LogOut, LogIn } from 'lucide-react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export function Header() {
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated, userEmail, logout } = useAuth();

  const handleLogout = () => {
    logout();
    navigate('/search');
  };

  const handleLoginClick = () => {
    navigate('/login');
  };

  const isAuditPage = location.pathname === '/audit';
  const isSearchPage = location.pathname === '/search';

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
                  className={`px-4 py-2 rounded-lg font-medium transition ${
                    isSearchPage
                      ? 'bg-blue-100 text-blue-700'
                      : 'text-gray-600 hover:bg-gray-100'
                  }`}
                >
                  Clasificar
                </Link>
                <Link
                  to="/audit"
                  className={`px-4 py-2 rounded-lg font-medium transition ${
                    isAuditPage
                      ? 'bg-blue-100 text-blue-700'
                      : 'text-gray-600 hover:bg-gray-100'
                  }`}
                >
                  Auditar
                </Link>
              </nav>
            )}

            <div className="border-l border-gray-200 pl-4 flex items-center gap-3">
              {isAuthenticated ? (
                <>
                  <span className="text-sm text-gray-600">{userEmail}</span>
                  <button
                    onClick={handleLogout}
                    className="flex items-center gap-2 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100 rounded-lg transition"
                  >
                    <LogOut className="w-4 h-4" />
                    Cerrar Sesión
                  </button>
                </>
              ) : (
                <button
                  onClick={handleLoginClick}
                  className="flex items-center gap-2 px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition"
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
