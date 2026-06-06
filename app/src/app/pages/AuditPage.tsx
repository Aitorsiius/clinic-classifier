import { useState } from 'react';
import { Header } from '../components/Header';
import { AuditPanel } from '../components/AuditPanel';
import { AuditResults, AuditReportData } from '../components/AuditResults';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';
import { useSession } from '../context/SessionContext';

export default function AuditPage() {
  const session = useSession();
  const [isLoading, setIsLoading] = useState(false);

  // Usar estado del contexto
  const auditReport = session.auditReport;
  const setAuditReport = session.setAuditReport;

  const handleAuditStart = async (auditResult: AuditReportData) => {
    setIsLoading(true);
    try {
      // Establecer el resultado de la auditoría en el contexto
      setAuditReport(auditResult);
      // Contabilizar la auditoría en las estadísticas de la sesión
      session.incrementStat('audits');
      // Limpiar el CSV después de completar la auditoría
      session.setCSVData(null);
      session.setFileName('');
    } catch (error) {
      console.error('Error en la auditoría:', error);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50">
      <Header />
      
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {!auditReport ? (
          <AuditPanel onAuditStart={handleAuditStart} />
        ) : (
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-3xl font-bold text-gray-900">Resultados de la Auditoría</h1>
                <p className="text-gray-600 mt-1">
                  ID de Informe: {auditReport.audit_id}
                </p>
              </div>
              <button
                onClick={() => setAuditReport(null)}
                className="rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 px-5 py-2.5 font-medium text-white shadow-lg shadow-blue-600/25 transition-all duration-200 hover:-translate-y-0.5 hover:from-blue-700 hover:to-indigo-700 hover:shadow-xl hover:shadow-blue-600/30 active:translate-y-0 active:scale-[0.98]"
              >
                Nueva Auditoría
              </button>
            </div>
            
            <AuditResults report={auditReport} />
          </div>
        )}
      </main>
    </div>
  );
}
