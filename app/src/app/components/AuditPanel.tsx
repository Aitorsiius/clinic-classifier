import { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Alert, AlertDescription } from './ui/alert';
import { Upload, FileText, AlertCircle, CheckCircle2, Zap, X } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useSession } from '../context/SessionContext';
import { AuditReportData } from './AuditResults';
import { AnimatedProcessButton } from './AnimatedProcessButton';
import { Filters } from './Filters';
import { scrollToRevealExpansion } from '../utils/scroll';
import { cleanDiagnosisText } from '../utils/format';

interface CSVRow {
  [key: string]: string;
}

// Evento recibido por el stream SSE de auditoría. Los campos son opcionales
// porque cada tipo de evento ('complete' | 'error' | 'progress') usa un
// subconjunto distinto.
interface AuditStreamEvent {
  type: string;
  result: AuditReportData;
  message: string;
  current: number;
  total: number;
}

interface AuditPanelProps {
  onAuditStart?: (auditReport: AuditReportData) => void;
}

export function AuditPanel({ onAuditStart }: Readonly<AuditPanelProps>) {
  const session = useSession();
  const [error, setError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const actionsRef = useRef<HTMLDivElement>(null);

  // Usar estado del contexto de sesión
  const csvData = session.csvData;
  const setCSVData = session.setCSVData;
  const fileName = session.fileName;
  const setFileName = session.setFileName;
  const topK = session.auditTopK;
  const setTopK = session.setAuditTopK;
  const useAI = session.auditUseAI;
  const setUseAI = session.setAuditUseAI;
  const isProcessing = session.isProcessing;
  const setIsProcessing = session.setIsProcessing;
  const progress = session.auditProgress;
  const setProgress = session.setAuditProgress;

  const { token } = useAuth();

  const API_GATEWAY_URL = import.meta.env.VITE_API_GATEWAY_URL;

  const isValidId = (id: string | null): boolean => {
    if (!id) return false;
    return /^[a-zA-Z0-9\-_]+$/.test(id);
  };

  useEffect(() => {
    const clearError = () => setError(null);
    globalThis.addEventListener('auth:logout', clearError);
    return () => globalThis.removeEventListener('auth:logout', clearError);
  }, []);

  // Al cargar un CSV, la vista previa y el botón de acción aparecen con una
  // animación de entrada; desplazamos la página EN PARALELO (al compás) para
  // que el botón "Iniciar Auditoría" quede visible sin saltos bruscos.
  useEffect(() => {
    if (csvData && csvData.length > 0) {
      const raf = requestAnimationFrame(() => {
        if (actionsRef.current) {
          scrollToRevealExpansion(actionsRef.current, 0, 450);
        }
      });
      return () => cancelAnimationFrame(raf);
    }
  }, [csvData]);

  // Tokeniza el contenido CSV respetando los campos entrecomillados: las comas y
  // los saltos de línea DENTRO de comillas dobles no separan campos/filas, y las
  // comillas escapadas ("") se interpretan como una comilla literal. Esto es
  // imprescindible porque "diagnosis_text" va entre comillas y contiene comas; un
  // split('\n')/split(',') ingenuo descartaría o partiría mal esas filas.
  const parseCSVRows = (content: string): string[][] => {
    const text = content.replace(/\r\n?/g, '\n');
    const rows: string[][] = [];
    let row: string[] = [];
    let field = '';
    let inQuotes = false;

    const endField = () => { row.push(field); field = ''; };
    const endRow = () => { endField(); rows.push(row); row = []; };

    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (inQuotes) {
        if (ch !== '"') { field += ch; }
        else if (text[i + 1] === '"') { field += '"'; i++; } // comilla escapada
        else { inQuotes = false; }
      } else if (ch === '"') {
        inQuotes = true;
      } else if (ch === ',') {
        endField();
      } else if (ch === '\n') {
        endRow();
      } else {
        field += ch;
      }
    }
    // Último campo/fila cuando el archivo no termina en salto de línea.
    if (field.length > 0 || row.length > 0) {
      endRow();
    }
    return rows;
  };

  const parseCSV = (content: string): CSVRow[] => {
    // Descartar filas totalmente vacías (líneas en blanco).
    const lines = parseCSVRows(content).filter(
      cells => cells.some(c => c.trim() !== '')
    );
    if (lines.length < 2) {
      throw new Error('El CSV debe contener encabezados y al menos una fila de datos');
    }

    const headers = lines[0].map(h => h.trim());
    const requiredHeaders = ['diagnosis_text', 'assigned_code'];

    const missingHeaders = requiredHeaders.filter(h => !headers.includes(h));
    if (missingHeaders.length > 0) {
      throw new Error(`Columnas requeridas faltantes: ${missingHeaders.join(', ')}`);
    }

    const data: CSVRow[] = [];
    for (let i = 1; i < lines.length; i++) {
      const values = lines[i];
      if (values.length !== headers.length) continue;

      const row: CSVRow = {};
      headers.forEach((header, index) => {
        row[header] = (values[index] ?? '').trim();
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

    if (e.dataTransfer.files?.[0]) {
      handleFileSelect(e.dataTransfer.files[0]);
    }
  };

  const handleTopKChange = (newTopK: number) => {
    setTopK(newTopK);
    session.setAuditTopK(newTopK);
  };

  // Aplica un evento SSE ya parseado al estado del componente. Un evento de
  // tipo 'error' lanza para que el bloque try/catch de quien lo invoca lo
  // registre (mismo comportamiento que antes de extraer esta función).
  const applyAuditEvent = (data: AuditStreamEvent) => {
    if (data.type === 'complete') {
      setProgress(100);
      onAuditStart?.(data.result);
      // La auditoría sigue en segundo plano aunque el usuario cambie de vista.
      // Si al terminar no está en la pantalla de auditoría, dejamos un aviso
      // visual en la barra de navegación.
      if (globalThis.location.pathname !== '/audit') {
        session.setAuditNotification(true);
      }
    } else if (data.type === 'error') {
      throw new Error(data.message);
    } else if (data.type === 'progress') {
      setProgress(Math.round((data.current / data.total) * 100));
    }
  };

  // Procesa una línea SSE completa ("data: {...}"). Los errores de parseo (y
  // los eventos 'error') se registran sin propagarse.
  const processSSELine = (line: string) => {
    if (!line.startsWith('data: ')) return;
    try {
      applyAuditEvent(JSON.parse(line.slice(6)));
    } catch (parseError) {
      console.error('Error parsing SSE data:', parseError);
    }
  };

  // Lee el cuerpo de la respuesta SSE en streaming y procesa cada línea
  // completa, manteniendo la última línea parcial en el buffer.
  const readAuditStream = async (reader: ReadableStreamDefaultReader<Uint8Array>) => {
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');

      // Procesar líneas completas (todas menos la última, potencialmente parcial).
      for (let i = 0; i < lines.length - 1; i++) {
        processSSELine(lines[i]);
      }

      // Mantener la última línea incompleta
      buffer = lines.at(-1) || '';
    }
  };

  const handleSubmit = async () => {
    if (!csvData || !token) return;

    setProgress(0);
    setIsProcessing(true);
    setError(null);
    // Marca de inicio para el cronómetro en vivo de la barra de progreso.
    session.setAuditStartTime(Date.now());

    // Controlador para poder cancelar la auditoría
    const controller = new AbortController();
    session.registerAuditController(controller);

    try {
      // Obtener user_id y session_id del localStorage
      const userId = isValidId(localStorage.getItem('user_id')) ? localStorage.getItem('user_id') : null;
      const sessionId = isValidId(localStorage.getItem('session_id')) ? localStorage.getItem('session_id') : null;

      const response = await fetch(`${API_GATEWAY_URL}/api/audit/batch-stream`, {
        method: 'POST',
        signal: controller.signal,
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
          'x-user-id': userId || '',
          'x-session-id': sessionId || ''
        },
        body: JSON.stringify({
          records: csvData,
          top_k: topK,
          use_ai: useAI
        })
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || 'Error en la auditoría');
      }

      // Procesar eventos SSE
      const reader = response.body?.getReader();
      if (!reader) throw new Error('La respuesta del servidor no contiene datos');

      await readAuditStream(reader);
    } catch (err) {
      // Cancelación voluntaria del usuario: no es un error, no mostrar alerta.
      if (err instanceof DOMException && err.name === 'AbortError') {
        return;
      }
      const errorMessage = err instanceof Error ? err.message : 'Ocurrió un error';
      setError(errorMessage);
    } finally {
      // Si esta ejecución fue cancelada, `cancelAudit()` ya reinició el estado y
      // el usuario puede haber lanzado una nueva auditoría. No tocamos el estado
      // compartido aquí para no pisar esa ejecución nueva (si lo hiciéramos,
      // `isProcessing` volvería a false y su barra de progreso se congelaría).
      if (!controller.signal.aborted) {
        session.registerAuditController(null);
        setIsProcessing(false);
        // Detener el cronómetro en vivo (los resultados muestran el tiempo final
        // autoritativo devuelto por el backend).
        session.setAuditStartTime(null);
      }
    }
  };

  // Cancela la auditoría en curso (aborta el stream y reinicia el progreso).
  const handleCancel = () => {
    setError(null);
    session.cancelAudit();
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
          topK={topK}
          setTopK={handleTopKChange}
          isLoading={isProcessing}
        />

        {/* Bloque IA: el panel y su aviso van juntos para que space-y-6 los
            trate como una sola unidad y el aviso quede pegado al panel. */}
        <div>
          {/* Modo IA: el panel ENTERO es clickable (alterna el modo IA). Ejecuta
              la auditoría a través del pipeline de búsqueda con IA (primera fase
              LLM que enriquece cada diagnóstico). Más preciso pero más lento. */}
          <button
            type="button"
            role="switch"
            aria-checked={useAI}
            onClick={() => setUseAI(!useAI)}
            disabled={isProcessing}
            className={`flex w-full items-center justify-between gap-4 rounded-lg border p-4 text-left transition-colors focus:outline-none focus:ring-2 focus:ring-purple-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60 ${
              useAI ? 'border-purple-300 bg-purple-50' : 'border-slate-200 bg-slate-50 hover:bg-slate-100'
            }`}
          >
            <span className="flex items-start gap-3">
              <Zap className={`mt-0.5 h-5 w-5 flex-shrink-0 ${useAI ? 'text-purple-600 fill-current' : 'text-slate-400'}`} />
              <span className="block">
                <span className="block text-sm font-semibold text-slate-800">Auditar con IA</span>
                <span className="block text-xs text-slate-500">
                  Enriquece cada diagnóstico con IA antes de clasificarlo. Mejora la precisión,
                  pero la auditoría tarda más por registro.
                </span>
              </span>
            </span>
            {/* Interruptor visual: el click lo gestiona el botón padre. */}
            <span
              aria-hidden="true"
              className={`relative inline-flex h-6 w-11 flex-shrink-0 items-center rounded-full transition-colors ${
                useAI ? 'bg-purple-600' : 'bg-slate-300'
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                  useAI ? 'translate-x-6' : 'translate-x-1'
                }`}
              />
            </span>
          </button>

          {/* Aviso: al usar IA se recuerda que puede cometer errores.
              Aparece y desaparece de forma suave (altura + opacidad). */}
          <AnimatePresence initial={false}>
            {useAI && (
              <motion.div
                key="ai-warning"
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.25, ease: 'easeInOut' }}
                className="overflow-hidden"
              >
                <p className="mt-2 flex items-center gap-1.5 text-xs text-amber-700">
                  <AlertCircle className="h-3.5 w-3.5 flex-shrink-0" />
                  La IA puede cometer errores. Revisa siempre los resultados antes de usarlos.
                </p>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

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
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease: 'easeOut' }}
            className="space-y-3"
          >
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
                  {csvData.slice(0, 5).map((row) => (
                    <tr key={`${row.assigned_code}-${row.diagnosis_text}`} className="border-b hover:bg-gray-50">
                      <td className="px-4 py-2 text-gray-900">{cleanDiagnosisText(row.diagnosis_text)}</td>
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
          </motion.div>
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
          <motion.div
            ref={actionsRef}
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease: 'easeOut', delay: 0.05 }}
            className="flex gap-3 scroll-mb-6"
          >
            <div className="flex-1">
              <AnimatedProcessButton
                onClick={handleSubmit}
                isProcessing={isProcessing}
                progress={progress}
                startTime={session.auditStartTime}
                disabled={false}
                label="Iniciar Auditoría"
              />
            </div>
            {isProcessing ? (
              <Button
                onClick={handleCancel}
                variant="destructive"
                className="h-auto gap-2"
              >
                <X className="h-4 w-4" />
                Cancelar Auditoría
              </Button>
            ) : (
              <Button
                onClick={() => {
                  setCSVData(null);
                  setFileName('');
                  session.setCSVData(null);
                  session.setFileName('');
                }}
                variant="outline"
                className="h-auto"
              >
                Limpiar
              </Button>
            )}
          </motion.div>
        )}
      </CardContent>
    </Card>
  );
}
