import { Search, Loader2, X, Zap } from 'lucide-react';
import { useEffect } from 'react';

interface SearchInputProps {
  value: string;
  onChange: (value: string) => void;
  onSearch: () => void;
  onClear: () => void;
  isLoading: boolean;
  useAI?: boolean;
  onUseAIChange?: (value: boolean) => void;
  isAuthenticated?: boolean;
}

export function SearchInput({ value, onChange, onSearch, onClear, isLoading, useAI = false, onUseAIChange, isAuthenticated = false }: SearchInputProps) {
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && e.ctrlKey) {
      onSearch();
    }
  };

  // Listener global para Ctrl + Enter desde cualquier lugar
  useEffect(() => {
    const handleGlobalKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Enter' && e.ctrlKey && value.trim() && !isLoading) {
        e.preventDefault();
        onSearch();
      }
    };

    window.addEventListener('keydown', handleGlobalKeyDown);
    return () => {
      window.removeEventListener('keydown', handleGlobalKeyDown);
    };
  }, [value, isLoading, onSearch]);

  return (
    <div className="bg-white rounded-xl shadow-md border border-slate-200 p-6 mb-8">
      <label htmlFor="diagnosis-input" className="block text-sm text-slate-700 mb-2">
        Introduce el diagnóstico:
      </label>
      
      <textarea
        id="diagnosis-input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Ej: Paciente presenta dolor agudo en el abdomen inferior con náuseas y vómitos..."
        className="w-full h-32 px-4 py-3 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none text-slate-900 placeholder:text-slate-400"
        disabled={isLoading}
      />

      <div className="flex items-center justify-between mt-4">
        <div className="flex items-center gap-3">
          <p className="text-xs text-slate-500">
            Presiona <kbd className="px-2 py-0.5 bg-slate-100 border border-slate-300 rounded text-slate-700">Ctrl</kbd> + <kbd className="px-2 py-0.5 bg-slate-100 border border-slate-300 rounded text-slate-700">Enter</kbd> para clasificar
          </p>
          
          {/* Botón de Usar IA */}
          <button
            onClick={() => onUseAIChange?.(!useAI)}
            disabled={isLoading || !isAuthenticated}
            className={`px-3 py-1 rounded-lg transition-colors flex items-center gap-2 text-sm font-medium ${
              useAI
                ? 'bg-purple-100 text-purple-700 hover:bg-purple-200 border border-purple-300'
                : 'bg-slate-100 text-slate-600 hover:bg-slate-200 border border-slate-300'
            } disabled:opacity-50 disabled:cursor-not-allowed`}
            title={isAuthenticated ? "Activar análisis inteligente con IA para mejorar la búsqueda" : "Inicia sesión para usar IA"}
          >
            <Zap className={`w-4 h-4 ${useAI ? 'fill-current' : ''}`} />
            Usar IA
          </button>
        </div>

        <div className="flex gap-2">
          {value && !isLoading && (
            <button
              onClick={onClear}
              className="px-4 py-2 text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-lg transition-colors flex items-center gap-2"
            >
              <X className="w-4 h-4" />
              Limpiar
            </button>
          )}
          
          <button
            onClick={onSearch}
            disabled={!value.trim() || isLoading}
            className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 px-6 py-2 font-medium text-white shadow-lg shadow-blue-600/25 transition-all duration-200 hover:-translate-y-0.5 hover:from-blue-700 hover:to-indigo-700 hover:shadow-xl hover:shadow-blue-600/30 active:translate-y-0 active:scale-[0.98] disabled:translate-y-0 disabled:cursor-not-allowed disabled:from-slate-300 disabled:to-slate-300 disabled:shadow-none"
          >
            {isLoading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Clasificando...
              </>
            ) : (
              <>
                <Search className="w-4 h-4" />
                Clasificar
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
