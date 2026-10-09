import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Bell, CheckCheck, RefreshCw } from 'lucide-react';
import api from '../api/client';
import type { Alert, PaginatedResponse } from '../api/types';

const SEV_BADGE: Record<string, string> = {
  critical: 'bg-red-100 text-red-600',
  warning:  'bg-amber-100 text-amber-700',
  info:     'bg-sky-100 text-sky-700',
};

const STATUS_BADGE: Record<string, string> = {
  open:         'bg-red-50 text-red-600',
  acknowledged: 'bg-amber-50 text-amber-600',
  resolved:     'bg-green-50 text-green-600',
};

function fetchAlerts(status: string, page: number): Promise<PaginatedResponse<Alert>> {
  return api.get('/alerts', { params: { status: status || undefined, page, per_page: 20 } })
    .then((r) => r.data);
}

export default function AlertsPage() {
  const [statusFilter, setStatusFilter] = useState('open');
  const [page, setPage] = useState(1);
  const qc = useQueryClient();

  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['alerts', statusFilter, page],
    queryFn: () => fetchAlerts(statusFilter, page),
    placeholderData: (prev) => prev,
  });

  const acknowledge = useMutation({
    mutationFn: (id: string) => api.put(`/alerts/${id}/acknowledge`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['alerts'] }),
  });

  const alerts = data?.items ?? [];
  const totalPages = data?.pages ?? 1;

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Alerts</h1>
          <p className="text-sm text-gray-500">{data?.total ?? '—'} alerts</p>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="flex items-center gap-2 text-sm text-gray-500 hover:text-brand-600 transition disabled:opacity-50"
        >
          <RefreshCw size={15} className={isFetching ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-1 bg-gray-100 p-1 rounded-lg w-fit">
        {['open', 'acknowledged', 'resolved', ''].map((s) => (
          <button
            key={s || 'all'}
            onClick={() => { setStatusFilter(s); setPage(1); }}
            className={`px-3 py-1.5 text-xs font-semibold rounded-md transition ${
              statusFilter === s ? 'bg-white text-gray-800 shadow-xs' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {s || 'All'}
          </button>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-gray-100 shadow-xs overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50">
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Severity</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Message</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Device</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Status</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Triggered</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {isLoading
              ? Array.from({ length: 6 }).map((_, i) => (
                  <tr key={i}>
                    {Array.from({ length: 6 }).map((_, j) => (
                      <td key={j} className="px-4 py-3">
                        <div className="h-4 bg-gray-100 rounded-sm animate-pulse" />
                      </td>
                    ))}
                  </tr>
                ))
              : alerts.map((a) => (
                  <tr key={a.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3">
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${SEV_BADGE[a.severity]}`}>
                        {a.severity}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-700 max-w-xs truncate">{a.message}</td>
                    <td className="px-4 py-3 text-gray-500 text-xs font-mono">{a.device_hostname ?? a.device_id.slice(0, 8)}</td>
                    <td className="px-4 py-3">
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${STATUS_BADGE[a.status]}`}>
                        {a.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-400 text-xs">
                      {new Date(a.triggered_at).toLocaleString()}
                    </td>
                    <td className="px-4 py-3">
                      {a.status === 'open' && (
                        <button
                          onClick={() => acknowledge.mutate(a.id)}
                          disabled={acknowledge.isPending}
                          title="Acknowledge"
                          className="p-1.5 rounded-sm hover:bg-brand-50 text-gray-400 hover:text-brand-600 transition"
                        >
                          <CheckCheck size={15} />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
          </tbody>
        </table>

        {!isLoading && alerts.length === 0 && (
          <div className="py-16 text-center text-gray-400">
            <Bell size={32} className="mx-auto mb-3 text-gray-200" />
            <p className="text-sm">No {statusFilter || ''} alerts.</p>
          </div>
        )}
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between text-sm text-gray-500">
          <span>Page {page} of {totalPages}</span>
          <div className="flex gap-2">
            <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}
              className="px-3 py-1.5 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40 transition">
              Previous
            </button>
            <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page === totalPages}
              className="px-3 py-1.5 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40 transition">
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
