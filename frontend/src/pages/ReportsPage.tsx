import { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { FileText, Download, RefreshCw, BarChart2 } from 'lucide-react';
import api from '../api/client';

interface ReportTemplate {
  id: string;
  name: string;
  description?: string;
  report_type: string;
}

interface Report {
  id: string;
  name: string;
  report_type: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  file_path?: string;
  created_at: string;
  completed_at?: string;
}

const STATUS_BADGE: Record<string, string> = {
  pending:   'bg-gray-100 text-gray-500',
  running:   'bg-blue-100 text-blue-600',
  completed: 'bg-green-100 text-green-700',
  failed:    'bg-red-100 text-red-600',
};

export default function ReportsPage() {
  const [generating, setGenerating] = useState<string | null>(null);

  const { data: templates, isLoading: templatesLoading } = useQuery<ReportTemplate[]>({
    queryKey: ['report-templates'],
    queryFn: () => api.get('/reports/templates').then((r) => r.data),
  });

  const { data: reports, isLoading: reportsLoading, refetch } = useQuery<Report[]>({
    queryKey: ['reports'],
    queryFn: () => api.get('/reports/').then((r) => r.data.items ?? r.data),
    refetchInterval: 10_000,
  });

  const generate = useMutation({
    mutationFn: (template_id: string) =>
      api.post('/reports/generate', { template_id }),
    onSuccess: () => {
      refetch();
      setGenerating(null);
    },
  });

  const handleDownload = async (id: string, name: string) => {
    const resp = await api.get(`/reports/${id}`, { responseType: 'blob' });
    const url = URL.createObjectURL(resp.data);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${name}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-bold text-gray-900">Reports</h1>
        <p className="text-sm text-gray-500">Generate and download system reports</p>
      </div>

      {/* Templates */}
      <div>
        <h2 className="text-sm font-semibold text-gray-700 mb-3">Available Reports</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {templatesLoading
            ? Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="h-24 bg-white border border-gray-100 rounded-xl animate-pulse" />
              ))
            : (templates ?? []).map((t) => (
                <div key={t.id} className="bg-white border border-gray-100 rounded-xl p-4 shadow-xs">
                  <div className="flex items-start gap-3">
                    <div className="w-8 h-8 bg-brand-50 rounded-lg flex items-center justify-center shrink-0">
                      <BarChart2 size={15} className="text-brand-500" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-semibold text-gray-800 text-sm">{t.name}</p>
                      {t.description && <p className="text-xs text-gray-400 mt-0.5 line-clamp-2">{t.description}</p>}
                      <button
                        onClick={() => { setGenerating(t.id); generate.mutate(t.id); }}
                        disabled={generate.isPending && generating === t.id}
                        className="mt-2 flex items-center gap-1.5 text-xs font-semibold text-brand-600 hover:text-brand-700 disabled:opacity-50 transition"
                      >
                        {generate.isPending && generating === t.id ? (
                          <RefreshCw size={12} className="animate-spin" />
                        ) : (
                          <FileText size={12} />
                        )}
                        Generate
                      </button>
                    </div>
                  </div>
                </div>
              ))}
        </div>
      </div>

      {/* Generated reports */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-gray-700">Generated Reports</h2>
          <button onClick={() => refetch()}
            className="flex items-center gap-2 text-sm text-gray-500 hover:text-brand-600 transition">
            <RefreshCw size={14} />
            Refresh
          </button>
        </div>
        <div className="bg-white rounded-xl border border-gray-100 shadow-xs overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Name</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Type</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Status</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Created</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {reportsLoading
                ? Array.from({ length: 4 }).map((_, i) => (
                    <tr key={i}>
                      {Array.from({ length: 5 }).map((_, j) => (
                        <td key={j} className="px-4 py-3">
                          <div className="h-4 bg-gray-100 rounded-sm animate-pulse" />
                        </td>
                      ))}
                    </tr>
                  ))
                : (reports ?? []).map((r) => (
                    <tr key={r.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3 font-medium text-gray-800">{r.name}</td>
                      <td className="px-4 py-3 text-gray-500 text-xs">{r.report_type}</td>
                      <td className="px-4 py-3">
                        <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${STATUS_BADGE[r.status]}`}>
                          {r.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-400">
                        {new Date(r.created_at).toLocaleString()}
                      </td>
                      <td className="px-4 py-3">
                        {r.status === 'completed' && (
                          <button
                            onClick={() => handleDownload(r.id, r.name)}
                            className="flex items-center gap-1.5 text-xs font-semibold text-brand-600 hover:text-brand-700 transition"
                          >
                            <Download size={13} />
                            Download
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
            </tbody>
          </table>
          {!reportsLoading && (reports ?? []).length === 0 && (
            <div className="py-12 text-center text-gray-400">
              <FileText size={32} className="mx-auto mb-3 text-gray-200" />
              <p className="text-sm">No reports generated yet.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
