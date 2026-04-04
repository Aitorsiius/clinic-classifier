import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Alert, AlertDescription } from './ui/alert';
import { Upload, FileText, AlertCircle, CheckCircle2 } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useSession } from '../context/SessionContext';
import { AuditReportData } from './AuditResults';
import { AnimatedProcessButton } from './AnimatedProcessButton';
import { Filters } from './Filters';

interface CSVRow {
  [key: string]: string;
}

interface AuditPanelProps {
  onAuditStart?: (auditReport: AuditReportData) => void;
}

export function AuditPanel({ onAuditStart }: AuditPanelProps) {
  const session = useSession();
  const [error, setError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);

  // Usar estado del contexto de sesión
  const csvData = session.csvData;
  const setCSVData = session.setCSVData;
  const fileName = session.fileName;
  const setFileName = session.setFileName;
  const algorithm = session.auditAlgorithm;
  const setAlgorithm = session.setAuditAlgorithm;
  const topK = session.auditTopK;
  const setTopK = session.setAuditTopK;
  const isProcessing = session.isProcessing;
  const setIsProcessing = session.setIsProcessing;
  const progress = session.auditProgress;
  const setProgress = session.setAuditProgress;

  const { token } = useAuth();

  const API_GATEWAY_URL = import.meta.env.VITE_API_GATEWAY_URL || 'http://localhost:3000';

  const parseCSV = (content: string): CSVRow[] => {
    const lines = content.trim().split('\n');
    if (lines.length < 2) {
      throw new Error('El CSV debe contener encabezados y al menos una fila de datos');
    }

    const headers = lines[0].split(',').map(h => h.trim());
    const requiredHeaders = ['diagnosis_text', 'assigned_code'];
    
    const missingHeaders = requiredHeaders.filter(h => !headers.includes(h));
    if (missingHeaders.length > 0) {
      throw new Error(`Columnas requeridas faltantes: ${missingHeaders.join(', ')}`);
    }

    const data: CSVRow[] = [];
    for (let i = 1; i < lines.length; i++) {
      const values = lines[i].split(',').map(v => v.trim());
      if (values.length !== headers.length) continue;

      const row: CSVRow = {};
      headers.forEach((header, index) => {
        row[header] = values[index];
      });
      data.push(row);
    }

    return data;
  };

  const handleFileSelect = async (file: File) => {
    setError(null);
    setCSVData(null);

    // Validar tipo de archivo
    if (!file.name.endsWith('.csv')) {
      setError('Solo se aceptan archivos CSV');
      return;
    }

    // Validar tamaño (máx 10MB)
    if (file.size > 10 * 1024 * 1024) {
      setError('El tamaño del archivo debe ser menor a 10MB');
      return;
    }

    try {
      const content = await file.text();
      const data = parseCSV(content);
      
      if (data.length === 0) {
        setError('El CSV no contiene filas de datos válidas');
        return;
      }

      setCSVData(data);
      setFileName(file.name);
      // Guardar en la sesión
      session.setCSVData(data);
      session.setFileName(file.name);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Error al procesar CSV';
      setError(errorMessage);
    }
  };

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(e.type === 'dragenter' || e.type === 'dragover');
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFileSelect(e.dataTransfer.files[0]);
    }
  };

  const handleAlgorithmChange = (newAlgo: string) => {
    setAlgorithm(newAlgo);
    session.setAuditAlgorithm(newAlgo);
  };

  const handleTopKChange = (newTopK: number) => {
    setTopK(newTopK);
    session.setAuditTopK(newTopK);
  };

  const handleSubmit = async () => {
    if (!csvData || !token) return;

    setIsProcessing(true);
    setError(null);

    try {
      const response = await fetch(`${API_GATEWAY_URL}/api/audit/batch-stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          records: csvData,
          algorithm: algorithm,
          top_k: topK
        })
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Error en la auditoría');
      }

      // Procesar eventos SSE
      const reader = response.body?.getReader();
      if (!reader) throw new Error('No response body');

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');

        // Procesar líneas completas
        for (let i = 0; i < lines.length - 1; i++) {
          const line = lines[i];
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              
              if (data.type === 'complete') {
                setProgress(100);
                onAuditStart?.(data.result);
              } else if (data.type === 'error') {
                throw new Error(data.message);
              } else if (data.type === 'progress') {
                setProgress(Math.round((data.current / data.total) * 100));
              }
            } catch (parseError) {
              console.error('Error parsing SSE data:', parseError);
            }
          }
        }

        // Mantener la última línea incompleta
        buffer = lines[lines.length - 1];
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Ocurrió un error';
      setError(errorMessage);
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Cargar Archivo de Auditoría</CardTitle>
        <CardDescription>
          Carga un archivo CSV con diagnósticos para auditar
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Sección de Filtros - Siempre visible */}
        <Filters
          algorithm={algorithm}
          setAlgorithm={handleAlgorithmChange}
          topK={topK}
          setTopK={handleTopKChange}
          isLoading={isProcessing}
        />

        {/* Área de Arrastra y Suelta */}
        <div
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
          className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
            dragActive
              ? 'border-blue-500 bg-blue-50'
              : 'border-gray-300 hover:border-gray-400'
          }`}
        >
          <Upload className="mx-auto h-12 w-12 text-gray-400 mb-4" />
          <p className="text-lg font-medium text-gray-700 mb-2">
            Arrastra tu archivo CSV aquí
          </p>
          <p className="text-sm text-gray-500 mb-4">
            o
          </p>
          <label>
            <input
              type="file"
              accept=".csv"
              onChange={(e) => e.target.files && handleFileSelect(e.target.files[0])}
              className="hidden"
            />
            <Button variant="outline" asChild className="cursor-pointer">
              <span>Seleccionar Archivo</span>
            </Button>
          </label>
        </div>

        {/* Vista Previa del CSV */}
        {csvData && (
          <div className="space-y-3">
            <div className="flex items-center gap-2 p-3 bg-green-50 rounded-lg border border-green-200">
              <CheckCircle2 className="h-5 w-5 text-green-600" />
              <div>
                <p className="font-medium text-green-900">{fileName}</p>
                <p className="text-sm text-green-700">{csvData.length} registros cargados</p>
              </div>
            </div>

            {/* Tabla de Vista Previa */}
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b">
                  <tr>
                    <th className="px-4 py-2 text-left font-medium text-gray-700">Diagnóstico</th>
                    <th className="px-4 py-2 text-left font-medium text-gray-700">Código</th>
                  </tr>
                </thead>
                <tbody>
                  {csvData.slice(0, 5).map((row, idx) => (
                    <tr key={idx} className="border-b hover:bg-gray-50">
                      <td className="px-4 py-2 text-gray-900">{row.diagnosis_text}</td>
                      <td className="px-4 py-2 font-mono text-gray-900">{row.assigned_code}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {csvData.length > 5 && (
                <p className="text-xs text-gray-500 mt-2 p-2">
                  ... y {csvData.length - 5} registros más
                </p>
              )}
            </div>
          </div>
        )}

        {/* Alerta de Error */}
        {error && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {/* Ayuda de Formato CSV */}
        {!csvData && (
          <div className="p-4 bg-blue-50 rounded-lg border border-blue-200">
            <h4 className="font-medium text-blue-900 mb-2 flex items-center gap-2">
              <FileText className="h-4 w-4" />
              Formato CSV Requerido
            </h4>
            <p className="text-sm text-blue-800 mb-2">Tu CSV debe contener estas columnas:</p>
            <ul className="text-sm text-blue-800 space-y-1 ml-4">
              <li>• <code className="bg-white px-2 py-1 rounded">diagnosis_text</code> - Descripción del diagnóstico clínico</li>
              <li>• <code className="bg-white px-2 py-1 rounded">assigned_code</code> - Código CIE-10 asignado</li>
              <li>• <code className="bg-white px-2 py-1 rounded">patient_id</code> - (Opcional) Identificador del paciente</li>
            </ul>
          </div>
        )}

        {/* Botones de Acción */}
        {csvData && (
          <div className="flex gap-3">
            <div className="flex-1">
              <AnimatedProcessButton
                onClick={handleSubmit}
                isProcessing={isProcessing}
                progress={progress}
                disabled={false}
                label="Iniciar Auditoría"
              />
            </div>
            <Button
              onClick={() => {
                setCSVData(null);
                setFileName('');
                session.setCSVData(null);
                session.setFileName('');
              }}
              variant="outline"
              disabled={isProcessing}
            >
              Limpiar
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
