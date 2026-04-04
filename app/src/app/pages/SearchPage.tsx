import { useState, useEffect } from 'react';
import { Header } from '../components/Header';
import { SearchInput } from '../components/SearchInput';
import { ResultsList } from '../components/ResultsList';
import { Filters } from '../components/Filters';
import { AIAnalysisPanel } from '../components/AIAnalysisPanel';
import { useSession } from '../context/SessionContext';

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
  const [error, setError] = useState<string | null>(null);

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
      // Realizar la búsqueda de clasificación (sin IA)
      const response = await fetch(`${API_GATEWAY_URL}/api/search`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
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
        />

        {aiAnalysis && <AIAnalysisPanel data={aiAnalysis} shouldCollapse={isLoading} />}

        <ResultsList results={results} isLoading={isLoading} useAI={useAI} />
      </main>
    </div>
  );
}
