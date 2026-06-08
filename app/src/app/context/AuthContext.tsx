import { createContext, useContext, useState, useEffect, useRef, ReactNode } from 'react';
import type { SessionStats } from './SessionContext';

interface UserData {
  username: string;
  admin: boolean;
  audit: boolean;
}

/**
 * Instantánea de la sesión capturada en el momento del logout. Se usa para
 * mostrar la pantalla de despedida con las estadísticas de la sesión antes de
 * limpiar el almacenamiento (que reinicia los contadores).
 */
export interface LogoutSummary {
  username: string;
  stats: SessionStats;
  elapsedMs: number;
}

const EMPTY_LOGOUT_STATS: SessionStats = {
  searches: 0,
  audits: 0,
  usersCreated: 0,
  passwordsChanged: 0,
  roleChanges: 0,
  usersDeleted: 0,
  usersUnblocked: 0,
};

interface AuthContextType {
  isAuthenticated: boolean;
  username: string | null;
  userData: UserData | null;
  token: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  skipLogoutDisplay: () => void;
  isLoading: boolean;
  isLoggingOut: boolean;
  logoutSummary: LogoutSummary | null;
  error: string | null;
}

// Duración (ms) de la animación de desvanecimiento al cerrar sesión
const LOGOUT_FADE_MS = 300;

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [username, setUsername] = useState<string | null>(null);
  const [userData, setUserData] = useState<UserData | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [logoutSummary, setLogoutSummary] = useState<LogoutSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Resolver que permite acortar la espera del overlay desde fuera del logout()
  const displayResolverRef = useRef<(() => void) | null>(null);

  /**
   * Cierra inmediatamente la pantalla de despedida sin esperar a que el
   * temporizador llegue a cero. El proceso de logout continúa normalmente
   * (limpieza de almacenamiento, reset de estado, etc.).
   */
  const skipLogoutDisplay = () => {
    if (displayResolverRef.current) {
      displayResolverRef.current();
      displayResolverRef.current = null;
    }
  };

  const API_GATEWAY_URL = import.meta.env.VITE_API_GATEWAY_URL || 'http://localhost:3000';

  // Verificar token al montar el componente
  useEffect(() => {
    const storedToken = localStorage.getItem('auth_token');
    const storedUsername = localStorage.getItem('user_username');
    const storedUserData = localStorage.getItem('user_data');
    
    if (storedToken && storedUsername) {
      setToken(storedToken);
      setUsername(storedUsername);
      if (storedUserData) {
        setUserData(JSON.parse(storedUserData));
      }
      setIsAuthenticated(true);
      
      // Verificar que el token siga siendo válido
      verifyToken(storedToken).catch(() => {
        localStorage.removeItem('auth_token');
        localStorage.removeItem('user_username');
        localStorage.removeItem('user_data');
        setIsAuthenticated(false);
        setToken(null);
        setUsername(null);
        setUserData(null);
      });
    }
  }, []);

  const verifyToken = async (tok: string) => {
    try {
      const response = await fetch(`${API_GATEWAY_URL}/api/verify-token`, {
        headers: {
          'Authorization': `Bearer ${tok}`
        }
      });
      
      if (!response.ok) {
        throw new Error('Verificación de token fallida');
      }
      
      return await response.json();
    } catch (err) {
      throw err;
    }
  };

  const login = async (username: string, password: string) => {
    setIsLoading(true);
    setError(null);
    
    try {
      const response = await fetch(`${API_GATEWAY_URL}/api/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ username, password })
      });

      if (!response.ok) {
        const data = await response.json();
        // Extraer el mensaje de error de forma segura
        let errorMsg = 'Error de autenticación';
        
        if (data && typeof data === 'object') {
          if (data.detail) {
            errorMsg = typeof data.detail === 'string' ? data.detail : 'Credenciales inválidas';
          } else if (data.message) {
            errorMsg = data.message;
          } else if (data.error) {
            errorMsg = data.error;
          }
        }
        
        throw new Error(errorMsg);
      }

      const data = await response.json();
      
      // Guardar token, username, datos del usuario y session_id
      localStorage.setItem('auth_token', data.access_token);
      localStorage.setItem('user_username', username);
      localStorage.setItem('user_data', JSON.stringify(data.user_data));
      if (data.session_id) {
        localStorage.setItem('session_id', data.session_id);
      }
      // Guardar user_id si está disponible en user_data
      if (data.user_data?.user_id) {
        localStorage.setItem('user_id', data.user_data.user_id);
      }
      
      setToken(data.access_token);
      setUsername(username);
      setUserData(data.user_data);
      setIsAuthenticated(true);

      // Notificar a la sesión que comienza una nueva sesión: reinicia las
      // estadísticas y marca el inicio para el resumen al cerrar sesión.
      window.dispatchEvent(new Event('auth:login'));
    } catch (err) {
      let errorMessage = 'Error de autenticación desconocido';
      
      if (err instanceof Error) {
        errorMessage = err.message;
      } else if (typeof err === 'string') {
        errorMessage = err;
      }
      
      setError(errorMessage);
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  const logout = async () => {
    // 1. Capturar una instantánea de la sesión ANTES de limpiar nada, para
    //    poder mostrar la pantalla de despedida con las estadísticas.
    const snapshotUsername =
      username || localStorage.getItem('user_username') || 'Usuario';

    let snapshotStats: SessionStats = EMPTY_LOGOUT_STATS;
    try {
      const rawStats = sessionStorage.getItem('session_stats');
      if (rawStats) {
        snapshotStats = { ...EMPTY_LOGOUT_STATS, ...JSON.parse(rawStats) };
      }
    } catch {
      snapshotStats = EMPTY_LOGOUT_STATS;
    }

    let elapsedMs = 0;
    const startedRaw = sessionStorage.getItem('session_startedAt');
    if (startedRaw) {
      const startedAt = parseInt(startedRaw, 10);
      if (!Number.isNaN(startedAt)) {
        elapsedMs = Math.max(0, Date.now() - startedAt);
      }
    }

    setLogoutSummary({
      username: snapshotUsername,
      stats: snapshotStats,
      elapsedMs,
    });

    // 2. Limpiar el estado de autenticación INMEDIATAMENTE para que cualquier
    //    navegación por URL (botón atrás, etc.) ya vea la sesión como cerrada.
    const token = localStorage.getItem('auth_token');
    const sessionId = localStorage.getItem('session_id');

    localStorage.removeItem('auth_token');
    localStorage.removeItem('user_username');
    localStorage.removeItem('user_data');
    localStorage.removeItem('session_id');
    localStorage.removeItem('user_id');

    // Limpiar también sessionStorage para eliminar búsquedas y auditorías
    sessionStorage.clear();

    // Disparar evento personalizado para limpiar las vistas
    window.dispatchEvent(new Event('auth:logout'));

    setToken(null);
    setUsername(null);
    setUserData(null);
    setIsAuthenticated(false);
    setError(null);

    // 3. Activar el overlay (despedida + estadísticas con animación de cartera)
    setIsLoggingOut(true);

    // 4. Cerrar la sesión en la API en segundo plano (no bloquea la animación).
    //    El api-gateway ya se encarga de avisar al log-service internamente,
    //    por lo que NO hay que llamar a /sessions/close directamente (evita 400).
    if (token && sessionId) {
      (async () => {
        try {
          await fetch(`${API_GATEWAY_URL}/api/logout?session_id=${sessionId}`, {
            method: 'POST',
            headers: {
              'Authorization': `Bearer ${token}`,
              'Content-Type': 'application/json',
            },
          });
        } catch (err) {
          console.error('Error logging out from API:', err);
        }
      })();
    }

    // 5. Mantener la despedida visible indefinidamente: la pantalla solo se
    //    cierra cuando el usuario pulsa la X (skipLogoutDisplay resuelve esta
    //    promesa). Así puede consultar sus estadísticas el tiempo que quiera.
    await new Promise<void>((resolve) => {
      displayResolverRef.current = resolve;
    });
    displayResolverRef.current = null;

    // Mantener el overlay mientras se navega y se reordena el layout,
    // después desvanecerlo suavemente para revelar la vista ya recolocada.
    setTimeout(() => {
      setIsLoggingOut(false);
      // Limpiar la instantánea una vez completado el desvanecimiento
      setTimeout(() => setLogoutSummary(null), LOGOUT_FADE_MS + 100);
    }, LOGOUT_FADE_MS + 100);
  };

  const value: AuthContextType = {
    isAuthenticated,
    username,
    userData,
    token,
    login,
    logout,
    skipLogoutDisplay,
    isLoading,
    isLoggingOut,
    logoutSummary,
    error
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
