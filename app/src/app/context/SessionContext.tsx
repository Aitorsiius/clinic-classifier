import React, { createContext, useContext, useState, useEffect, useMemo } from 'react';

interface DiagnosisResult {
  score: number;
  payload: {
    id: string;
    title: string;
    metadata: {
      hierarchy: Array<{
        code: string;
        title: string;
      }>;
    };
  };
}

interface CSVRow {
  [key: string]: string;
}

/**
 * Estadísticas acumuladas de la sesión actual. Se usan para mostrar un resumen
 * al cerrar sesión. Las búsquedas no distinguen entre con/sin IA (todo junto).
 */
export interface SessionStats {
  searches: number;
  audits: number;
  usersCreated: number;
  passwordsChanged: number;
  roleChanges: number;
  usersDeleted: number;
  usersUnblocked: number;
}

export type SessionStatKey = keyof SessionStats;

const EMPTY_SESSION_STATS: SessionStats = {
  searches: 0,
  audits: 0,
  usersCreated: 0,
  passwordsChanged: 0,
  roleChanges: 0,
  usersDeleted: 0,
  usersUnblocked: 0,
};

interface SessionContextType {
  // Clasificación (Search)
  searchText: string;
  setSearchText: (text: string) => void;
  results: DiagnosisResult[];
  setResults: (results: DiagnosisResult[]) => void;
  topK: number;
  setTopK: (k: number) => void;
  useAI: boolean;
  setUseAI: (use: boolean) => void;
  aiAnalysis: any;
  setAiAnalysis: (analysis: any) => void;
  // Tiempo total (ms) de la última búsqueda devuelto por el backend (con o sin
  // IA). Se muestra junto a los resultados.
  searchTimeMs: number | null;
  setSearchTimeMs: (ms: number | null) => void;
  isLoading: boolean;
  setIsLoading: (loading: boolean) => void;

  // Auditoría
  csvData: CSVRow[] | null;
  setCSVData: (data: CSVRow[] | null) => void;
  fileName: string;
  setFileName: (name: string) => void;
  auditTopK: number;
  setAuditTopK: (k: number) => void;
  // Ejecuta la auditoría a través del pipeline de búsqueda con IA.
  auditUseAI: boolean;
  setAuditUseAI: (use: boolean) => void;
  isProcessing: boolean;
  setIsProcessing: (processing: boolean) => void;
  auditProgress: number;
  setAuditProgress: (progress: number) => void;
  // Marca de tiempo (ms epoch) de inicio de la auditoría en curso. Permite
  // mostrar un cronómetro en vivo en la barra de progreso que sobrevive a la
  // navegación entre vistas.
  auditStartTime: number | null;
  setAuditStartTime: (ts: number | null) => void;
  auditReport: any;
  setAuditReport: (report: any) => void;
  // Aviso visual: una auditoría finalizó mientras el usuario estaba en otra vista
  auditNotification: boolean;
  setAuditNotification: (value: boolean) => void;
  // Aviso visual: una búsqueda finalizó mientras el usuario estaba en otra vista
  searchNotification: boolean;
  setSearchNotification: (value: boolean) => void;

  // Estadísticas de la sesión (para el resumen al cerrar sesión)
  sessionStats: SessionStats;
  incrementStat: (key: SessionStatKey) => void;
  sessionStartedAt: number;

  // Limpiar sesión
  clearSession: () => void;
}

const SessionContext = createContext<SessionContextType | undefined>(undefined);

export function SessionProvider({ children }: Readonly<{ children: React.ReactNode }>) {
  // Clasificación
  const [searchText, setSearchText] = useState('');
  const [results, setResults] = useState<DiagnosisResult[]>([]);
  const [topK, setTopK] = useState(5);
  const [useAI, setUseAI] = useState(false);
  const [aiAnalysis, setAiAnalysis] = useState<any>(null);
  const [searchTimeMs, setSearchTimeMs] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  // Auditoría
  const [csvData, setCSVData] = useState<CSVRow[] | null>(null);
  const [fileName, setFileName] = useState('');
  const [auditTopK, setAuditTopK] = useState(5);
  const [auditUseAI, setAuditUseAI] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [auditProgress, setAuditProgress] = useState(0);
  const [auditStartTime, setAuditStartTime] = useState<number | null>(null);
  const [auditReport, setAuditReport] = useState<any>(null);
  // Aviso pendiente de "auditoría finalizada" para la barra de navegación
  const [auditNotification, setAuditNotification] = useState(false);
  // Aviso pendiente de "búsqueda finalizada" para la barra de navegación
  const [searchNotification, setSearchNotification] = useState(false);

  // Estadísticas de la sesión (para el resumen al cerrar sesión)
  const [sessionStats, setSessionStats] = useState<SessionStats>(EMPTY_SESSION_STATS);
  const [sessionStartedAt, setSessionStartedAt] = useState<number>(() => {
    const saved = sessionStorage.getItem('session_startedAt');
    if (saved) return Number.parseInt(saved, 10);
    const now = Date.now();
    sessionStorage.setItem('session_startedAt', String(now));
    return now;
  });

  // Incrementa en uno el contador de una estadística de la sesión
  const incrementStat = (key: SessionStatKey) => {
    setSessionStats((prev: SessionStats) => ({ ...prev, [key]: prev[key] + 1 }));
  };

  // Función para limpiar todos los estados
  const resetAllStates = () => {
    setSearchText('');
    setResults([]);
    setTopK(5);
    setUseAI(false);
    setAiAnalysis(null);
    setSearchTimeMs(null);
    setIsLoading(false);
    setCSVData(null);
    setFileName('');
    setAuditTopK(5);
    setAuditUseAI(false);
    setIsProcessing(false);
    setAuditProgress(0);
    setAuditStartTime(null);
    setAuditReport(null);
    setAuditNotification(false);
    setSearchNotification(false);
    // Reiniciar estadísticas y la marca de inicio de la sesión
    setSessionStats(EMPTY_SESSION_STATS);
    const now = Date.now();
    setSessionStartedAt(now);
    sessionStorage.setItem('session_startedAt', String(now));
  };

  const isValidJWT = (token: string | null): boolean => {
    if (!token) return false;
    // Verifica que tenga la estructura clásica: header.payload.signature
    return /^[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+\.[A-Za-z0-9-_]*$/.test(token);
  };

  // Detectar logout y limpiar sesión automáticamente
  useEffect(() => {
    const handleStorageChange = (e: StorageEvent) => {
      // Si se borra el token de autenticación, limpiar todo
      if (e.key === 'auth_token' && e.newValue === null) {
        resetAllStates();
      }
    };

    const handleLogout = () => {
      resetAllStates();
    };

    const handleLogin = () => {
      // Nueva sesión: reiniciar estadísticas y marcar el inicio de la sesión
      setSessionStats(EMPTY_SESSION_STATS);
      const now = Date.now();
      setSessionStartedAt(now);
      sessionStorage.setItem('session_startedAt', String(now));
    };

    // Escuchar eventos de storage (funciona entre pestañas)
    globalThis.addEventListener('storage', handleStorageChange);
    
    // Escuchar eventos personalizados de login/logout (misma pestaña)
    globalThis.addEventListener('auth:logout', handleLogout);
    globalThis.addEventListener('auth:login', handleLogin);

    // También verificar al montar si no hay token
    const token = isValidJWT(localStorage.getItem('auth_token')) ? localStorage.getItem('auth_token') : null;
    if (!token) {
      resetAllStates();
    }

    return () => {
      globalThis.removeEventListener('storage', handleStorageChange);
      globalThis.removeEventListener('auth:logout', handleLogout);
      globalThis.removeEventListener('auth:login', handleLogin);
    };
  }, []);

  // Cargar desde sessionStorage al montar el componente (solo si hay token)
  useEffect(() => {
    // Restaura un valor de sessionStorage solo si existe, delegando el parseo
    // al callback. Así el efecto queda como una lista plana de restauraciones.
    const restore = (key: string, apply: (raw: string) => void) => {
      const raw = sessionStorage.getItem(key);
      if (raw) apply(raw);
    };

    restore('session_searchText', setSearchText);
    restore('session_results', (raw) => setResults(JSON.parse(raw)));
    restore('session_topK', (raw) => setTopK(Number.parseInt(raw)));
    restore('session_useAI', (raw) => setUseAI(raw === 'true'));
    restore('session_aiAnalysis', (raw) => setAiAnalysis(JSON.parse(raw)));
    restore('session_searchTimeMs', (raw) => setSearchTimeMs(raw === 'null' ? null : Number.parseFloat(raw)));
    restore('session_isLoading', (raw) => setIsLoading(raw === 'true'));
    restore('session_csvData', (raw) => setCSVData(JSON.parse(raw)));
    restore('session_fileName', setFileName);
    restore('session_auditTopK', (raw) => setAuditTopK(Number.parseInt(raw)));
    restore('session_auditUseAI', (raw) => setAuditUseAI(raw === 'true'));
    restore('session_isProcessing', (raw) => setIsProcessing(raw === 'true'));
    restore('session_auditProgress', (raw) => setAuditProgress(Number.parseInt(raw)));
    restore('session_auditStartTime', (raw) => setAuditStartTime(raw === 'null' ? null : Number.parseInt(raw, 10)));
    restore('session_auditReport', (raw) => setAuditReport(JSON.parse(raw)));
    restore('session_auditNotification', (raw) => setAuditNotification(raw === 'true'));
    restore('session_searchNotification', (raw) => setSearchNotification(raw === 'true'));

    // Restaurar estadísticas de la sesión (si existen)
    restore('session_stats', (raw) => {
      try {
        setSessionStats({ ...EMPTY_SESSION_STATS, ...JSON.parse(raw) });
      } catch {
        setSessionStats(EMPTY_SESSION_STATS);
      }
    });
  }, []);

  // Guardar en sessionStorage cuando cambian los valores
  useEffect(() => {
    sessionStorage.setItem('session_searchText', searchText);
  }, [searchText]);

  useEffect(() => {
    sessionStorage.setItem('session_results', JSON.stringify(results));
  }, [results]);

  useEffect(() => {
    sessionStorage.setItem('session_topK', topK.toString());
  }, [topK]);

  useEffect(() => {
    sessionStorage.setItem('session_useAI', useAI.toString());
  }, [useAI]);

  useEffect(() => {
    sessionStorage.setItem('session_aiAnalysis', JSON.stringify(aiAnalysis));
  }, [aiAnalysis]);

  useEffect(() => {
    sessionStorage.setItem('session_searchTimeMs', searchTimeMs === null ? 'null' : String(searchTimeMs));
  }, [searchTimeMs]);

  useEffect(() => {
    sessionStorage.setItem('session_isLoading', isLoading.toString());
  }, [isLoading]);

  useEffect(() => {
    if (csvData) {
      sessionStorage.setItem('session_csvData', JSON.stringify(csvData));
    } else {
      sessionStorage.removeItem('session_csvData');
    }
  }, [csvData]);

  useEffect(() => {
    sessionStorage.setItem('session_fileName', fileName);
  }, [fileName]);

  useEffect(() => {
    sessionStorage.setItem('session_auditTopK', auditTopK.toString());
  }, [auditTopK]);

  useEffect(() => {
    sessionStorage.setItem('session_auditUseAI', auditUseAI.toString());
  }, [auditUseAI]);

  useEffect(() => {
    sessionStorage.setItem('session_isProcessing', isProcessing.toString());
  }, [isProcessing]);

  useEffect(() => {
    sessionStorage.setItem('session_auditProgress', auditProgress.toString());
  }, [auditProgress]);

  useEffect(() => {
    sessionStorage.setItem('session_auditStartTime', auditStartTime === null ? 'null' : String(auditStartTime));
  }, [auditStartTime]);

  useEffect(() => {
    if (auditReport) {
      sessionStorage.setItem('session_auditReport', JSON.stringify(auditReport));
    } else {
      sessionStorage.removeItem('session_auditReport');
    }
  }, [auditReport]);

  useEffect(() => {
    sessionStorage.setItem('session_auditNotification', auditNotification.toString());
  }, [auditNotification]);

  useEffect(() => {
    sessionStorage.setItem('session_searchNotification', searchNotification.toString());
  }, [searchNotification]);

  // Persistir las estadísticas de la sesión para que sobrevivan a recargas
  useEffect(() => {
    sessionStorage.setItem('session_stats', JSON.stringify(sessionStats));
  }, [sessionStats]);

  const clearSession = () => {
    setSearchText('');
    setResults([]);
    setTopK(5);
    setUseAI(false);
    setAiAnalysis(null);
    setSearchTimeMs(null);
    setIsLoading(false);
    setCSVData(null);
    setFileName('');
    setAuditTopK(5);
    setAuditUseAI(false);
    setIsProcessing(false);
    setAuditProgress(0);
    setAuditStartTime(null);
    setAuditReport(null);
    setAuditNotification(false);
    setSearchNotification(false);
    setSessionStats(EMPTY_SESSION_STATS);
    sessionStorage.clear();
  };

  const value = useMemo<SessionContextType>(
    () => ({
      searchText,
      setSearchText,
      results,
      setResults,
      topK,
      setTopK,
      useAI,
      setUseAI,
      aiAnalysis,
      setAiAnalysis,
      searchTimeMs,
      setSearchTimeMs,
      isLoading,
      setIsLoading,
      csvData,
      setCSVData,
      fileName,
      setFileName,
      auditTopK,
      setAuditTopK,
      auditUseAI,
      setAuditUseAI,
      isProcessing,
      setIsProcessing,
      auditProgress,
      setAuditProgress,
      auditStartTime,
      setAuditStartTime,
      auditReport,
      setAuditReport,
      auditNotification,
      setAuditNotification,
      searchNotification,
      setSearchNotification,
      sessionStats,
      incrementStat,
      sessionStartedAt,
      clearSession,
    }),
    [
      searchText,
      results,
      topK,
      useAI,
      aiAnalysis,
      searchTimeMs,
      isLoading,
      csvData,
      fileName,
      auditTopK,
      auditUseAI,
      isProcessing,
      auditProgress,
      auditStartTime,
      auditReport,
      auditNotification,
      searchNotification,
      sessionStats,
      incrementStat,
      sessionStartedAt,
      clearSession,
    ]
  );

  return (
    <SessionContext.Provider value={value}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionContextType {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error('useSession debe usarse dentro de SessionProvider');
  }
  return context;
}
