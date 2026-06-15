import { useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/tabs';
import { Badge } from './ui/badge';
import { Input } from './ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from './ui/select';
import { Download, FileJson, TrendingUp, AlertTriangle, CheckCircle2, Search, X } from 'lucide-react';
import { formatDuration } from '../utils/format';

export interface AuditResult {
  patient_id: string;
  diagnosis_text: string;
  assigned_code: string;
  suggested_code: string;
  discrepancy_type: string;
  confidence_score: number;
  match_score: number;
  explanation: string;
  alternative_codes: string[];
}

export interface AuditReportData {
  audit_id: string;
  timestamp: string;
  total_records: number;
  total_correct: number;
  total_partial_match: number;
  total_mismatch: number;
  conformity_percentage: number;
  top_k?: number;
  // Tiempo total (ms) del lote de auditoría devuelto por el backend.
  total_time_ms?: number;
  findings: AuditResult[];
}

interface AuditResultsProps {
  report: AuditReportData;
}

const DiscrepancyTypeColors: Record<string, string> = {
  'coincidencia': 'bg-green-100 text-green-800',
  'parcialmente': 'bg-yellow-100 text-yellow-800',
  'no_coincidencia': 'bg-red-100 text-red-800',
};

const DiscrepancyTypeIcons: Record<string, React.ReactNode> = {
  'coincidencia': <CheckCircle2 className="h-4 w-4" />,
  'parcialmente': <AlertTriangle className="h-4 w-4" />,
  'no_coincidencia': <AlertTriangle className="h-4 w-4" />,
};

const DiscrepancyTypeBorderColors: Record<string, string> = {
  'coincidencia': '#22c55e',      // green-500
  'parcialmente': '#eab308',      // yellow-500
  'no_coincidencia': '#ef4444',   // red-500
};

export function AuditResults({ report }: AuditResultsProps) {
  const [filterType, setFilterType] = useState<string | null>(null);
  const [filterCode, setFilterCode] = useState<string>('');
  const [sortBy, setSortBy] = useState<'code' | 'score' | 'type'>('code');

  const filteredFindings = useMemo(() => {
    let results = [...report.findings]; // Creamos una copia para evitar mutar el report original con el .sort()

    if (filterType) {
      results = results.filter(f => f.discrepancy_type === filterType);
    }

    if (filterCode.trim()) {
      const searchTerm = filterCode.toLowerCase().trim();
      results = results.filter(f => 
        (f.assigned_code && f.assigned_code.toLowerCase().includes(searchTerm)) ||
        (f.suggested_code && f.suggested_code.toLowerCase().includes(searchTerm)) ||
        (f.alternative_codes && f.alternative_codes.some(code => code && code.toLowerCase().includes(searchTerm))) ||
        (f.diagnosis_text && f.diagnosis_text.toLowerCase().includes(searchTerm)) ||
        (f.patient_id && f.patient_id.toLowerCase().includes(searchTerm)) ||
        (f.discrepancy_type && f.discrepancy_type.toLowerCase().includes(searchTerm)) ||
        (f.explanation && f.explanation.toLowerCase().includes(searchTerm))
      );
    }

    // Ordenar resultados
    if (sortBy === 'score') {
      results.sort((a, b) => b.confidence_score - a.confidence_score);
    } else if (sortBy === 'type') {
      results.sort((a, b) => a.discrepancy_type.localeCompare(b.discrepancy_type));
    } else if (sortBy === 'code') {
      results.sort((a, b) => (a.assigned_code || '').localeCompare(b.assigned_code || ''));
    }

    return results;
  }, [report.findings, filterType, filterCode, sortBy]);

  const downloadJSON = () => {
    const dataStr = JSON.stringify(report, null, 2);
    const dataBlob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(dataBlob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `audit-report-${report.audit_id}.json`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const downloadCSV = () => {
    let csv = 'ID Paciente,Diagnóstico,Código Asignado,Código Sugerido,Códigos Alternativos,Tipo,Confianza,Puntuación Coincidencia\n';
    
    report.findings.forEach(f => {
      const alternativesStr = f.alternative_codes.join(';');
      csv += `"${f.patient_id}","${f.diagnosis_text}","${f.assigned_code}","${f.suggested_code}","${alternativesStr}","${f.discrepancy_type}",${f.confidence_score.toFixed(2)},${f.match_score.toFixed(2)}\n`;
    });

    const dataBlob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(dataBlob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `reporte-auditoria-${report.audit_id}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6">
      {/* Estadísticas Resumidas */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <Card>
          <CardContent className="pt-6">
            <div className="text-center">
              <div className="text-3xl font-bold text-blue-600">{report.total_records}</div>
              <p className="text-sm text-gray-600 mt-2">Total de Registros</p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-6">
            <div className="text-center">
              <div className="text-3xl font-bold text-green-600">{report.total_correct}</div>
              <p className="text-sm text-gray-600 mt-2">Correctos</p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-6">
            <div className="text-center">
              <div className="text-3xl font-bold text-yellow-600">{report.total_partial_match}</div>
              <p className="text-sm text-gray-600 mt-2">Coincidencia Parcial</p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-6">
            <div className="text-center">
              <div className="text-3xl font-bold text-red-600">{report.total_mismatch}</div>
              <p className="text-sm text-gray-600 mt-2">No Coincide</p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-6">
            <div className="text-center">
              <div className="text-3xl font-bold text-purple-600">
                {report.conformity_percentage.toFixed(1)}%
              </div>
              <p className="text-sm text-gray-600 mt-2">Conformidad</p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-6">
            <div className="text-center">
              <div className="text-2xl font-bold text-slate-700">
                {formatDuration(report.total_time_ms)}
              </div>
              <p className="text-sm text-gray-600 mt-2">Tiempo</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Tarjeta de Resultados */}
      <Card>
        <CardHeader>
          <CardTitle>Hallazgos de Auditoría</CardTitle>
          <CardDescription>
            {filteredFindings.length} de {report.findings.length} registros mostrados
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Controles */}
          <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between pb-4 border-b">
            <div className="flex flex-col sm:flex-row gap-4 flex-1 w-full">
              {/* Filtro de Código */}
              <div className="w-full sm:w-48 relative">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400" />
                  <Input
                    type="text"
                    placeholder="Buscar"
                    value={filterCode}
                    onChange={(e) => setFilterCode(e.target.value)}
                    className="pl-10 pr-8"
                  />
                  {filterCode && (
                    <button
                      onClick={() => setFilterCode('')}
                      className="absolute right-3 top-1/2 transform -translate-y-1/2 text-gray-400 hover:text-gray-600"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  )}
                </div>
              </div>

              <div className="w-full sm:w-48">
                <Select value={filterType || 'all'} onValueChange={(v) => setFilterType(v === 'all' ? null : v)}>
                  <SelectTrigger>
                    <SelectValue placeholder="Filtrar por tipo..." />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Todos los Tipos</SelectItem>
                    <SelectItem value="coincidencia">Coincidencia</SelectItem>
                    <SelectItem value="parcialmente">Parcialmente</SelectItem>
                    <SelectItem value="no_coincidencia">No Coincidencia</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="w-full sm:w-48">
                <Select value={sortBy} onValueChange={(v: any) => setSortBy(v)}>
                  <SelectTrigger>
                    <SelectValue placeholder="Ordenar por..." />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="code">Código</SelectItem>
                    <SelectItem value="score">Puntuación de Confianza</SelectItem>
                    <SelectItem value="type">Tipo</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="flex gap-2 w-full sm:w-auto">
              <Button
                onClick={downloadJSON}
                size="sm"
                variant="outline"
                className="flex-1 sm:flex-none"
              >
                <FileJson className="h-4 w-4 mr-2" />
                JSON
              </Button>
              <Button
                onClick={downloadCSV}
                size="sm"
                variant="outline"
                className="flex-1 sm:flex-none"
              >
                <Download className="h-4 w-4 mr-2" />
                CSV
              </Button>
            </div>
          </div>

          {/* Tabla de Resultados */}
          <Tabs defaultValue="table" className="w-full">
            <TabsList>
              <TabsTrigger value="table">Vista de Lista</TabsTrigger>
              <TabsTrigger value="list">Vista de Tabla</TabsTrigger>
            </TabsList>

            <TabsContent value="table" className="overflow-x-auto overflow-y-hidden">
              <table className="w-full text-sm table-fixed min-w-[59.375rem]">
                <thead className="bg-gray-50 border-b sticky top-0">
                  <tr>
                    <th className="px-4 py-2 text-left font-medium text-gray-700 w-[10%]">ID Paciente</th>
                    <th className="px-4 py-2 text-left font-medium text-gray-700 w-[22%]">Diagnóstico</th>
                    <th className="px-4 py-2 text-left font-medium text-gray-700 w-[15%]">Código Esperado</th>
                    <th className="px-4 py-2 text-left font-medium text-gray-700 w-[15%]">Código Resultante</th>
                    <th className="px-4 py-2 text-left font-medium text-gray-700 w-[16%]">Tipo</th>
                    <th className="px-4 py-2 text-right font-medium text-gray-700 w-[12%]">Confianza</th>
                  </tr>
                </thead>
                <tbody>
                <AnimatePresence>
                  {filteredFindings.map((finding, idx) => (
                    <motion.tr 
                      key={`${finding.patient_id}-${finding.assigned_code}`} 
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      transition={{ duration: 0.2 }}
                      className="border-b hover:bg-gray-50 transition-colors"
                    >
                      <td className="px-4 py-3 text-gray-900 font-medium text-sm">{finding.patient_id}</td>
                      <td className="px-4 py-3 text-gray-900 truncate text-sm" title={finding.diagnosis_text}>{finding.diagnosis_text}</td>
                      <td className="px-4 py-3 font-mono font-semibold text-gray-800">
                        {finding.assigned_code || '—'}
                      </td>
                      <td className="px-4 py-3 font-mono font-semibold text-gray-800">
                        {finding.suggested_code || '—'}
                      </td>
                      <td className="px-4 py-3">
                        <Badge className={DiscrepancyTypeColors[finding.discrepancy_type]} variant="default">
                          {finding.discrepancy_type}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-right font-mono font-bold text-blue-600">{finding.confidence_score.toFixed(2)}</td>
                    </motion.tr>
                  ))}
                </AnimatePresence>
                </tbody>
              </table>
            </TabsContent>

            <TabsContent value="list" className="flex flex-col gap-4">
              <AnimatePresence>
                {filteredFindings.map((finding, idx) => (
                  <motion.div
                    key={`${finding.patient_id}-${finding.assigned_code}`}
                    layout
                    initial={{ opacity: 0, height: 0, scale: 0.95 }}
                    animate={{ opacity: 1, height: 'auto', scale: 1 }}
                    exit={{ opacity: 0, height: 0, scale: 0.95 }}
                    transition={{ duration: 0.2 }}
                    className="overflow-hidden overflow-y-hidden"
                  >
                    <Card className="p-4 border-l-4" style={{
                      borderLeftColor: DiscrepancyTypeBorderColors[finding.discrepancy_type] || '#9ca3af'
                    }}>
                      <div className="space-y-4">
                        {/* Encabezado: Diagnóstico y tipo */}
                        <div className="flex items-start justify-between gap-4">
                          <div className="flex-1">
                            <p className="font-semibold text-gray-900 text-base">{finding.diagnosis_text}</p>
                            <p className="text-sm text-gray-500 mt-1">ID Paciente: <span className="font-mono font-medium">{finding.patient_id}</span></p>
                          </div>
                          <Badge className={DiscrepancyTypeColors[finding.discrepancy_type]} variant="default">
                            {DiscrepancyTypeIcons[finding.discrepancy_type]}
                            <span className="ml-2">{finding.discrepancy_type}</span>
                          </Badge>
                        </div>

                        {/* Sección de Códigos CIE-10 */}
                        <div className="bg-gray-50 rounded-lg p-4 space-y-3">
                          <p className="text-xs font-bold text-gray-700 uppercase tracking-wider">Códigos CIE-10</p>
                          
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                            {/* Código Asignado */}
                            <div className="bg-white rounded border-2 border-gray-200 p-3">
                              <p className="text-xs text-gray-700 font-semibold mb-1">Código Asignado</p>
                              <div className="flex items-center gap-2">
                                <code className="text-lg font-bold text-gray-800 bg-gray-50 px-3 py-1 rounded">
                                  {finding.assigned_code || '—'}
                                </code>
                              </div>
                            </div>

                            {/* Código Sugerido */}
                            {finding.suggested_code && (
                              <div className="bg-white rounded border-2 border-gray-200 p-3">
                                <p className="text-xs text-gray-700 font-semibold mb-1">Código Sugerido</p>
                                <div className="flex items-center gap-2">
                                  <code className="text-lg font-bold text-gray-800 bg-gray-50 px-3 py-1 rounded">
                                    {finding.suggested_code}
                                  </code>
                                </div>
                              </div>
                            )}
                          </div>

                          {/* Códigos Alternativos */}
                          {finding.alternative_codes.length > 0 && (
                            <div className="bg-white rounded border-2 border-blue-200 p-3">
                              <p className="text-xs text-blue-700 font-semibold mb-2">
                                Códigos Alternativos {(Boolean(report.top_k) && `(${finding.alternative_codes.length} candidatos)`)}
                              </p>
                              <div className="flex flex-wrap gap-2">
                                {finding.alternative_codes.map((code, i) => {
                                  const isAssignedCode = code === finding.assigned_code;
                                  return (
                                    <Badge 
                                      key={i} 
                                      variant="outline" 
                                      className={`text-sm font-mono ${
                                        isAssignedCode 
                                          ? 'bg-purple-100 text-purple-900 border-purple-400 ring-2 ring-purple-300' 
                                          : 'bg-blue-50 text-blue-800 border-blue-300'
                                      }`}
                                      title={isAssignedCode ? 'Código asignado encontrado en resultados' : ''}
                                    >
                                      {code}
                                      {isAssignedCode && ' ✓'}
                                    </Badge>
                                  );
                                })}
                              </div>
                            </div>
                          )}
                        </div>

                        {/* Puntuaciones */}
                        <div className="grid grid-cols-2 md:grid-cols-3 gap-3 bg-blue-50 rounded-lg p-3">
                          <div>
                            <p className="text-xs font-semibold text-blue-700">Confianza</p>
                            <p className="text-lg font-bold text-blue-900">{finding.confidence_score.toFixed(2)}</p>
                          </div>
                          <div>
                            <p className="text-xs font-semibold text-blue-700">Tipo Discrepancia</p>
                            <p className="text-sm font-mono text-blue-900">{finding.discrepancy_type}</p>
                          </div>
                        </div>

                        {/* Explicación */}
                        {finding.explanation && (
                          <div className="bg-amber-50 rounded-lg p-3 border border-amber-200">
                            <p className="text-xs font-semibold text-amber-700 mb-1">Explicación</p>
                            <p className="text-sm text-amber-900">{finding.explanation}</p>
                          </div>
                        )}
                      </div>
                    </Card>
                  </motion.div>
                ))}
              </AnimatePresence>
              
              {filteredFindings.length === 0 && (
                <div className="text-center py-8">
                  <p className="text-gray-500">No hay hallazgos que mostrar con los filtros seleccionados</p>
                </div>
              )}
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  );
}
