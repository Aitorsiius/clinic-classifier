import { useState, useEffect } from 'react';
import { Clock, Sparkles } from 'lucide-react';

interface SearchHistoryItem {
  search_id: string;
  query: string;
  timestamp: string;
  results_count: number;
  results: any[];
  used_ai_assistant: boolean;
  ai_suggestions?: any;
  status: string;
  top_k?: number;
  session_id: string;
}

interface SearchHistoryData {
  user_id: string;
  total: number;
  history: {
    last_hour: SearchHistoryItem[];
    last_day: SearchHistoryItem[];
    last_week: SearchHistoryItem[];
    last_month: SearchHistoryItem[];
    last_year: SearchHistoryItem[];
    older: SearchHistoryItem[];
  };
  generated_at: string;
}

interface SearchHistoryProps {
  isOpen: boolean;
  onClose: () => void;
  onSelectSearch: (search: SearchHistoryItem) => void;
}

const API_GATEWAY_URL = import.meta.env.VITE_API_GATEWAY_URL

const isValidJWT = (token: string | null): boolean => {
    if (!token) return false;
    // Verifica que tenga la estructura clásica: header.payload.signature
    return /^[A-Za-z0-9-_]+\.[A-Za-z0-9-_]+\.[A-Za-z0-9-_]*$/.test(token);
};

const TIME_SEGMENTS = [
  { key: 'last_hour', label: 'Última hora' },
  { key: 'last_day', label: 'Último día' },
  { key: 'last_week', label: 'Última semana' },
  { key: 'last_month', label: 'Último mes' },
  { key: 'last_year', label: 'Último año' },
  { key: 'older', label: 'Más antiguo' },
];

export function SearchHistory({ isOpen, onClose, onSelectSearch }: SearchHistoryProps) {
  const [historyData, setHistoryData] = useState<SearchHistoryData | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Bloquear el scroll del body cuando el modal está abierto. Para evitar que
  // el contenido "salte" de tamaño al desaparecer/reaparecer la barra de scroll
  // vertical, se compensa su ancho con un padding-right equivalente y se
  // restauran los valores originales al cerrar.
  useEffect(() => {
    if (!isOpen) return;

    const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth;
    const previousOverflow = document.body.style.overflow;
    const previousPaddingRight = document.body.style.paddingRight;

    document.body.style.overflow = 'hidden';
    if (scrollbarWidth > 0) {
      document.body.style.paddingRight = `${scrollbarWidth}px`;
    }

    // Cleanup: restaurar el scroll y el padding al cerrar o desmontar
    return () => {
      document.body.style.overflow = previousOverflow;
      document.body.style.paddingRight = previousPaddingRight;
    };
  }, [isOpen]);

  useEffect(() => {
    if (isOpen) {
      fetchHistory();
    }
  }, [isOpen]);

  const fetchHistory = async () => {
    setIsLoading(true);
    setError(null);

    try {
      const token = isValidJWT(localStorage.getItem('auth_token')) ? localStorage.getItem('auth_token') : null;
      if (!token) {
        throw new Error('No authentication token found');
      }

      const response = await fetch(`${API_GATEWAY_URL}/api/search-history`, {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        throw new Error(`Error: ${response.status}`);
      }

      const data: SearchHistoryData = await response.json();
      setHistoryData(data);
    } catch (err) {
      console.error('Error fetching search history:', err);
      setError(err instanceof Error ? err.message : 'Error al cargar historial');
    } finally {
      setIsLoading(false);
    }
  };

  const formatDate = (isoDate: string) => {
    const date = new Date(isoDate);
    const day = date.getDate().toString().padStart(2, '0');
    const month = (date.getMonth() + 1).toString().padStart(2, '0');
    const year = date.getFullYear();
    const hours = date.getHours().toString().padStart(2, '0');
    const minutes = date.getMinutes().toString().padStart(2, '0');

    // Día de la semana en español (Lunes, Martes...) con la inicial en mayúscula
    const weekdayRaw = date.toLocaleDateString('es-ES', { weekday: 'long' });
    const weekday = weekdayRaw.charAt(0).toUpperCase() + weekdayRaw.slice(1);

    return `${weekday}, ${day}/${month}/${year} ${hours}:${minutes}`;
  };

  const truncateQuery = (query: string, maxLength: number = 80) => {
    if (query.length <= maxLength) return query;
    return query.substring(0, maxLength) + '...';
  };

  const handleSearchClick = (search: SearchHistoryItem) => {
    onSelectSearch(search);
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-gray-200 dark:border-gray-700">
          <div className="flex items-center gap-3">
            <Clock className="w-6 h-6 text-blue-600 dark:text-blue-400" />
            <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
              Historial de Búsquedas
            </h2>
          </div>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200 text-2xl font-bold"
          >
            ×
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {isLoading && (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
            </div>
          )}

          {error && (
            <div className="text-center py-12">
              <p className="text-red-600 dark:text-red-400">{error}</p>
              <button
                onClick={fetchHistory}
                className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
              >
                Reintentar
              </button>
            </div>
          )}

          {!isLoading && !error && historyData && (
            <div className="space-y-8">
              {historyData.total === 0 ? (
                <div className="text-center py-12">
                  <p className="text-gray-500 dark:text-gray-400 text-lg">
                    No hay búsquedas en el historial
                  </p>
                </div>
              ) : (
                TIME_SEGMENTS.map(segment => {
                  const searches = historyData.history[segment.key as keyof typeof historyData.history];
                  
                  if (!searches || searches.length === 0) return null;

                  return (
                    <div key={segment.key} className="space-y-4">
                      <h3 className="text-lg font-semibold text-gray-700 dark:text-gray-300 border-b border-gray-300 dark:border-gray-600 pb-2">
                        {segment.label}
                      </h3>
                      <div className="space-y-3">
                        {searches.map((search) => (
                          <button
                            key={search.search_id}
                            onClick={() => handleSearchClick(search)}
                            className={`w-full text-left p-4 rounded-lg transition-all duration-200 hover:shadow-lg ${
                              search.used_ai_assistant
                                ? 'border-2 border-purple-400 dark:border-purple-500 bg-purple-50 dark:bg-purple-900/20 hover:bg-purple-100 dark:hover:bg-purple-900/30'
                                : 'border-2 border-blue-400 dark:border-blue-500 bg-blue-50 dark:bg-blue-900/20 hover:bg-blue-100 dark:hover:bg-blue-900/30'
                            }`}
                          >
                            <div className="flex items-start justify-between gap-4">
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 mb-2">
                                  {search.used_ai_assistant && (
                                    <Sparkles className="w-4 h-4 text-purple-600 dark:text-purple-400 flex-shrink-0" />
                                  )}
                                  <p className="text-sm text-gray-500 dark:text-gray-400">
                                    {formatDate(search.timestamp)}
                                  </p>
                                </div>
                                <p className="text-base font-medium text-gray-900 dark:text-white mb-1">
                                  {truncateQuery(search.query)}
                                </p>
                                <p className="text-sm text-gray-600 dark:text-gray-400">
                                  {search.results_count} resultado{search.results_count !== 1 ? 's' : ''}
                                </p>
                              </div>
                              {search.used_ai_assistant && (
                                <div className="flex-shrink-0 px-3 py-1 bg-purple-200 dark:bg-purple-700 text-purple-800 dark:text-purple-200 text-xs font-semibold rounded-full">
                                  Con IA
                                </div>
                              )}
                            </div>
                          </button>
                        ))}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-gray-200 dark:border-gray-700 p-4 bg-gray-50 dark:bg-gray-900/50">
          <button
            onClick={onClose}
            className="w-full px-4 py-2 bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-300 dark:hover:bg-gray-600 transition-colors"
          >
            Cerrar
          </button>
        </div>
      </div>
    </div>
  );
}
