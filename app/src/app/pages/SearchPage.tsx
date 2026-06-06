import { useState, useEffect } from 'react';
import { Header } from '../components/Header';
import { SearchInput } from '../components/SearchInput';
import { ResultsList } from '../components/ResultsList';
import { Filters } from '../components/Filters';
import { AIAnalysisPanel } from '../components/AIAnalysisPanel';
import { SearchHistory } from '../components/SearchHistory';
import { useSession } from '../context/SessionContext';
import { useAuth } from '../context/AuthContext';
import { Clock } from 'lucide-react';

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
}

// Configuración de API
const API_GATEWAY_URL = import.meta.env.VITE_API_GATEWAY_URL || 'http://localhost:3000';

export default function SearchPage() {
  const session = useSession();
  const { isAuthenticated } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);

  // Usar valores del contexto de sesión
  const searchText = session.searchText;
  const setSearchText = session.setSearchText;
  const results = session.results;
  const setResults = session.setResults;
  const algorithm = session.algorithm;
  const setAlgorithm = session.setAlgorithm;
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
      const sessionId = localStorage.getItem('session_id');
      const userId = localStorage.getItem('user_id');
      
      // Realizar la búsqueda de clasificación (sin IA)
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
          algorithm: algorithm
        })
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Error: ${response.status}`);
      }

      const data: SearchResponse = await response.json();
      setResults(data.results);

      // Contabilizar la búsqueda en las estadísticas de la sesión
      // (no se distingue entre búsquedas con o sin IA, todo en conjunto)
      session.incrementStat('searches');

      // Si el usuario activó "Usar IA", obtener análisis en paralelo (independiente)
      if (useAI) {
        try {
          const llmResponse = await fetch(`${API_GATEWAY_URL}/api/process-query`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({
              query: searchText
            })
          });

          if (llmResponse.ok) {
            const llmData = await llmResponse.json();
            setAiAnalysis(llmData);
            
            // Registrar el análisis de IA en el log-service
            const sessionId = localStorage.getItem('session_id');
            if (sessionId) {
              try {
                await fetch(`${API_GATEWAY_URL}/api/log/update-ai`, {
                  method: 'PATCH',
                  headers: {
                    'Content-Type': 'application/json',
                  },
                  body: JSON.stringify({
                    session_id: sessionId,
                    query: searchText,
                    ai_analysis: llmData
                  })
                });
              } catch (logErr) {
                console.error('Error registering AI analysis in logs:', logErr);
                // No afecta la experiencia del usuario si falla el logging
              }
            }
          } else {
            const errorData = await llmResponse.json().catch(() => ({}));
            const errorMessage = errorData.detail || `Error ${llmResponse.status}: Fallo en el análisis de IA`;
            console.error('LLM Error:', errorMessage);
            // Si falla el LLM, no afecta la clasificación pero mostramos el error en consola
          }
        } catch (err) {
          console.error('Error processing with LLM:', err);
          // Si falla el LLM, no afecta la clasificación
        }
      }

      // Notificar al finalizar TODO el proceso (resultados + IA si estaba activa).
      // Se coloca aquí, al final del bloque de éxito, para que el badge solo
      // aparezca cuando la búsqueda está completamente resuelta.
      if (window.location.pathname !== '/search') {
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
  };

  const handleSelectSearch = (search: any) => {
    // Restaurar el estado de la búsqueda seleccionada
    setSearchText(search.query);
    setResults(search.results || []);
    
    // Si la búsqueda usó IA, restaurar el análisis
    if (search.used_ai_assistant && search.ai_suggestions) {
      setUseAI(true);
      setAiAnalysis({
        original_query: search.ai_suggestions.original_query,
        corrected_query: search.ai_suggestions.corrected_query,
        analysis: {
          primary_symptoms: search.ai_suggestions.primary_symptoms || [],
          secondary_symptoms: search.ai_suggestions.secondary_symptoms || [],
          search_keywords: search.ai_suggestions.search_keywords || []
        },
        processing_time_ms: search.ai_suggestions.processing_time_ms
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
              <Clock className="h-5 w-5 transition-transform duration-300 group-hover:-rotate-12" />
              <span>Ver Historial</span>
            </button>
          </div>
        )}

        <Filters
          algorithm={algorithm}
          setAlgorithm={setAlgorithm}
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

        <ResultsList results={results} isLoading={isLoading} useAI={useAI} />
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
