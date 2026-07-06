import { useState, useEffect } from 'react';
import { Header } from '../components/Header';
import { SearchInput } from '../components/SearchInput';
import { ResultsList } from '../components/ResultsList';
import { Filters } from '../components/Filters';
import { AIAnalysisPanel } from '../components/AIAnalysisPanel';
import { SearchHistory } from '../components/SearchHistory';
import { HistoryClockIcon } from '../components/HistoryClockIcon';
import { useSession } from '../context/SessionContext';
import { useAuth } from '../context/AuthContext';

export interface DiagnosisResult {
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

interface SearchResponse {
  results: DiagnosisResult[];
  query: string;
  count: number;
  used_ai?: boolean;
  // Tiempo total (ms) del pipeline de búsqueda en el backend (con o sin IA).
  search_time_ms?: number;
  // Bloque del asistente inteligente (solo en modo IA).
  assistant?: {
    diagnosis: string;
    improvement_tips: string[];
    enriched_query?: string;
    is_valid_medical_query?: boolean;
    processing_time_ms?: number;
  } | null;
}

// Configuración de API
const API_GATEWAY_URL = import.meta.env.VITE_API_GATEWAY_URL;

const isValidId = (id: string | null): boolean => {
  if (!id) return false;
  return /^[a-zA-Z0-9\-_]+$/.test(id);
};

export default function SearchPage() {
  const session = useSession();
  const { isAuthenticated } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);

  useEffect(() => {
    const clearError = () => setError(null);
    globalThis.addEventListener('auth:logout', clearError);
    return () => globalThis.removeEventListener('auth:logout', clearError);
  }, []);

  // Usar valores del contexto de sesión
  const searchText = session.searchText;
  const setSearchText = session.setSearchText;
  const results = session.results;
  const setResults = session.setResults;
  const topK = session.topK;
  const setTopK = session.setTopK;
  const useAI = session.useAI;
  const setUseAI = session.setUseAI;
  const aiAnalysis = session.aiAnalysis;
  const setAiAnalysis = session.setAiAnalysis;
  const isLoading = session.isLoading;
  const setIsLoading = session.setIsLoading;

  const handleSearch = async () => {
    if (!searchText.trim()) return;

    setIsLoading(true);
    setError(null);
    
    try {
      // Obtener session_id y user_id del localStorage
      const sessionId = isValidId(localStorage.getItem('session_id')) ? localStorage.getItem('session_id') : null;
      const userId = isValidId(localStorage.getItem('user_id')) ? localStorage.getItem('user_id') : null;

      // Realizar la búsqueda de clasificación. En modo IA el backend ejecuta la
      // primera fase (LLM) que enriquece la consulta y devuelve, además de los
      // resultados con su estructura habitual, el bloque del asistente.
      const response = await fetch(`${API_GATEWAY_URL}/api/search`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(sessionId && { 'x-session-id': sessionId }),
          ...(userId && { 'x-user-id': userId })
        },
        body: JSON.stringify({
          query: searchText,
          top_k: topK,
          use_ai: useAI
        })
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Error: ${response.status}`);
      }

      const data: SearchResponse = await response.json();
      setResults(data.results);

      // Guardar el tiempo total de la búsqueda (lo mide el backend e incluye,
      // en modo IA, la fase de enriquecimiento). Se muestra junto a los
      // resultados tanto en modo IA como sin IA.
      session.setSearchTimeMs(data.search_time_ms ?? null);

      // Contabilizar la búsqueda en las estadísticas de la sesión
      // (no se distingue entre búsquedas con o sin IA, todo en conjunto)
      session.incrementStat('searches');

      // En modo IA, el asistente viaja dentro de la respuesta de búsqueda
      // (una sola llamada). Si no hay bloque, se limpia el panel.
      if (useAI) {
        setAiAnalysis(data.assistant ?? null);
      } else {
        setAiAnalysis(null);
      }

      // Notificar al finalizar TODO el proceso (resultados + IA si estaba activa).
      // Se coloca aquí, al final del bloque de éxito, para que el badge solo
      // aparezca cuando la búsqueda está completamente resuelta.
      if (globalThis.location.pathname !== '/search') {
        session.setSearchNotification(true);
      }

    } catch (err) {
      console.error('Error searching:', err);
      setError(err instanceof Error ? err.message : 'Error al realizar la búsqueda');
      setResults([]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleClear = () => {
    setSearchText('');
    setResults([]);
    setError(null);
    setAiAnalysis(null);
    session.setSearchTimeMs(null);
  };

  const handleSelectSearch = (search: any) => {
    // Restaurar el estado de la búsqueda seleccionada
    setSearchText(search.query);
    setResults(search.results || []);

    // Restaurar el tiempo total de la búsqueda guardado en el historial.
    session.setSearchTimeMs(search.search_time_ms ?? null);
    
    // Si la búsqueda usó IA, restaurar el bloque del asistente (formato:
    // diagnóstico + consejos de mejora).
    if (search.used_ai_assistant && search.ai_suggestions) {
      setUseAI(true);
      setAiAnalysis({
        diagnosis: search.ai_suggestions.diagnosis || '',
        improvement_tips: search.ai_suggestions.improvement_tips || [],
        enriched_query: search.ai_suggestions.enriched_query,
        is_valid_medical_query: search.ai_suggestions.is_valid_medical_query,
        processing_time_ms: search.ai_suggestions.processing_time_ms,
      });
    } else {
      setUseAI(false);
      setAiAnalysis(null);
    }
    
    // Restaurar top_k si está disponible
    if (search.top_k) {
      setTopK(search.top_k);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50">
      <Header />
      
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {error && (
          <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">
            <strong>Error:</strong> {error}
          </div>
        )}
        
        {/* Botón de historial (solo visible si está autenticado) - Encima de Filtros */}
        {isAuthenticated && (
          <div className="mb-6 flex justify-center">
            <button
              onClick={() => setIsHistoryOpen(true)}
              className="group flex min-w-[12.5rem] items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 px-8 py-2.5 font-medium text-white shadow-lg shadow-blue-600/25 transition-all duration-200 hover:-translate-y-0.5 hover:from-blue-700 hover:to-indigo-700 hover:shadow-xl hover:shadow-blue-600/30 active:translate-y-0 active:scale-[0.98]"
            >
              <HistoryClockIcon className="h-5 w-5" />
              <span>Ver Historial</span>
            </button>
          </div>
        )}

        <Filters
          topK={topK}
          setTopK={setTopK}
          isLoading={isLoading}
        />

        <SearchInput
          value={searchText}
          onChange={setSearchText}
          onSearch={handleSearch}
          onClear={handleClear}
          isLoading={isLoading}
          useAI={useAI}
          onUseAIChange={setUseAI}
          isAuthenticated={isAuthenticated}
        />

        {aiAnalysis && <AIAnalysisPanel data={aiAnalysis} shouldCollapse={isLoading} />}

        <ResultsList results={results} isLoading={isLoading} useAI={useAI} searchTimeMs={session.searchTimeMs} />
      </main>

      {/* Modal de historial */}
      <SearchHistory
        isOpen={isHistoryOpen}
        onClose={() => setIsHistoryOpen(false)}
        onSelectSearch={handleSelectSearch}
      />
    </div>
  );
}
