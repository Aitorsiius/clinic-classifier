import React, { createContext, useContext, useState, useEffect } from 'react';

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

interface SessionContextType {
  // Clasificación (Search)
  searchText: string;
  setSearchText: (text: string) => void;
  results: DiagnosisResult[];
  setResults: (results: DiagnosisResult[]) => void;
  algorithm: string;
  setAlgorithm: (algo: string) => void;
  topK: number;
  setTopK: (k: number) => void;
  useAI: boolean;
  setUseAI: (use: boolean) => void;
  aiAnalysis: any;
  setAiAnalysis: (analysis: any) => void;
  isLoading: boolean;
  setIsLoading: (loading: boolean) => void;

  // Auditoría
  csvData: CSVRow[] | null;
  setCSVData: (data: CSVRow[] | null) => void;
  fileName: string;
  setFileName: (name: string) => void;
  auditAlgorithm: string;
  setAuditAlgorithm: (algo: string) => void;
  auditTopK: number;
  setAuditTopK: (k: number) => void;
  isProcessing: boolean;
  setIsProcessing: (processing: boolean) => void;
  auditProgress: number;
  setAuditProgress: (progress: number) => void;
  auditReport: any;
  setAuditReport: (report: any) => void;

  // Limpiar sesión
  clearSession: () => void;
}

const SessionContext = createContext<SessionContextType | undefined>(undefined);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  // Clasificación
  const [searchText, setSearchText] = useState('');
  const [results, setResults] = useState<DiagnosisResult[]>([]);
  const [algorithm, setAlgorithm] = useState('algoritmo1');
  const [topK, setTopK] = useState(5);
  const [useAI, setUseAI] = useState(false);
  const [aiAnalysis, setAiAnalysis] = useState<any>(null);
  const [isLoading, setIsLoading] = useState(false);

  // Auditoría
  const [csvData, setCSVData] = useState<CSVRow[] | null>(null);
  const [fileName, setFileName] = useState('');
  const [auditAlgorithm, setAuditAlgorithm] = useState('algoritmo1');
  const [auditTopK, setAuditTopK] = useState(5);
  const [isProcessing, setIsProcessing] = useState(false);
  const [auditProgress, setAuditProgress] = useState(0);
  const [auditReport, setAuditReport] = useState<any>(null);

  // Cargar desde sessionStorage al montar el componente
  useEffect(() => {
    const savedSearchText = sessionStorage.getItem('session_searchText');
    const savedResults = sessionStorage.getItem('session_results');
    const savedAlgorithm = sessionStorage.getItem('session_algorithm');
    const savedTopK = sessionStorage.getItem('session_topK');
    const savedUseAI = sessionStorage.getItem('session_useAI');
    const savedAiAnalysis = sessionStorage.getItem('session_aiAnalysis');
    const savedIsLoading = sessionStorage.getItem('session_isLoading');
    const savedCSVData = sessionStorage.getItem('session_csvData');
    const savedFileName = sessionStorage.getItem('session_fileName');
    const savedAuditAlgorithm = sessionStorage.getItem('session_auditAlgorithm');
    const savedAuditTopK = sessionStorage.getItem('session_auditTopK');
    const savedIsProcessing = sessionStorage.getItem('session_isProcessing');
    const savedAuditProgress = sessionStorage.getItem('session_auditProgress');
    const savedAuditReport = sessionStorage.getItem('session_auditReport');

    if (savedSearchText) setSearchText(savedSearchText);
    if (savedResults) setResults(JSON.parse(savedResults));
    if (savedAlgorithm) setAlgorithm(savedAlgorithm);
    if (savedTopK) setTopK(parseInt(savedTopK));
    if (savedUseAI) setUseAI(savedUseAI === 'true');
    if (savedAiAnalysis) setAiAnalysis(JSON.parse(savedAiAnalysis));
    if (savedIsLoading) setIsLoading(savedIsLoading === 'true');
    if (savedCSVData) setCSVData(JSON.parse(savedCSVData));
    if (savedFileName) setFileName(savedFileName);
    if (savedAuditAlgorithm) setAuditAlgorithm(savedAuditAlgorithm);
    if (savedAuditTopK) setAuditTopK(parseInt(savedAuditTopK));
    if (savedIsProcessing) setIsProcessing(savedIsProcessing === 'true');
    if (savedAuditProgress) setAuditProgress(parseInt(savedAuditProgress));
    if (savedAuditReport) setAuditReport(JSON.parse(savedAuditReport));
  }, []);

  // Guardar en sessionStorage cuando cambian los valores
  useEffect(() => {
    sessionStorage.setItem('session_searchText', searchText);
  }, [searchText]);

  useEffect(() => {
    sessionStorage.setItem('session_results', JSON.stringify(results));
  }, [results]);

  useEffect(() => {
    sessionStorage.setItem('session_algorithm', algorithm);
  }, [algorithm]);

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
    sessionStorage.setItem('session_auditAlgorithm', auditAlgorithm);
  }, [auditAlgorithm]);

  useEffect(() => {
    sessionStorage.setItem('session_auditTopK', auditTopK.toString());
  }, [auditTopK]);

  useEffect(() => {
    sessionStorage.setItem('session_isProcessing', isProcessing.toString());
  }, [isProcessing]);

  useEffect(() => {
    sessionStorage.setItem('session_auditProgress', auditProgress.toString());
  }, [auditProgress]);

  useEffect(() => {
    if (auditReport) {
      sessionStorage.setItem('session_auditReport', JSON.stringify(auditReport));
    } else {
      sessionStorage.removeItem('session_auditReport');
    }
  }, [auditReport]);

  const clearSession = () => {
    setSearchText('');
    setResults([]);
    setAlgorithm('algoritmo1');
    setTopK(5);
    setUseAI(false);
    setAiAnalysis(null);
    setIsLoading(false);
    setCSVData(null);
    setFileName('');
    setAuditAlgorithm('algoritmo1');
    setAuditTopK(5);
    setIsProcessing(false);
    setAuditProgress(0);
    setAuditReport(null);
    sessionStorage.clear();
  };

  const value: SessionContextType = {
    searchText,
    setSearchText,
    results,
    setResults,
    algorithm,
    setAlgorithm,
    topK,
    setTopK,
    useAI,
    setUseAI,
    aiAnalysis,
    setAiAnalysis,
    isLoading,
    setIsLoading,
    csvData,
    setCSVData,
    fileName,
    setFileName,
    auditAlgorithm,
    setAuditAlgorithm,
    auditTopK,
    setAuditTopK,
    isProcessing,
    setIsProcessing,
    auditProgress,
    setAuditProgress,
    auditReport,
    setAuditReport,
    clearSession,
  };

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
