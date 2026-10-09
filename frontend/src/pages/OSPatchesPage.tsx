import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Shield, CheckCircle, RefreshCw } from 'lucide-react';
import api from '../api/client';

interface PatchSummary {
  total_pending: number;
  total_installed: number;
  total_failed: number;
  by_device: Array<{ device_id: string; hostname: string; pending: number; failed: number }>;
}

interface Patch {
  id: string;
  device_id: string;
  device_hostname?: string;
  patch_id: string;
  title: string;
  severity: string;
  status: 'pending' | 'approved' | 'installed' | 'failed' | 'excluded';
  kb_article?: string;
  size_mb?: number;
  discovered_at: string;
}

interface PatchesResponse {
  items: Patch[];
  total: number;
  pages: number;
  page: number;
  per_page: number;
}

const SEV_BADGE: Record<string, string> = {
  critical:  'bg-red-100 text-red-600',
  important: 'bg-orange-100 text-orange-600',
  moderate:  'bg-amber-100 text-amber-700',
  low:       'bg-gray-100 text-gray-500',
  unspecified: 'bg-gray-100 text-gray-400',
};

const STATUS_BADGE: Record<string, string> = {
  pending:   'bg-amber-100 text-amber-700',
  approved:  'bg-blue-100 text-blue-700',
  installed: 'bg-green-100 text-green-700',
  failed:    'bg-red-100 text-red-600',
  excluded:  'bg-gray-100 text-gray-400',
};

export default function OSPatchesPage() {
  const [statusFilter, setStatusFilter] = useState('pending');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const qc = useQueryClient();

  const { data: summary } = useQuery<PatchSummary>({
    queryKey: ['patch-summary'],
    queryFn: () => api.get('/patches/summary').then((r) => r.data),
    refetchInterval: 60_000,
  });

  const { data, isLoading, isFetching, refetch } = useQuery<PatchesResponse>({
    queryKey: ['patches', statusFilter, page],
    queryFn: () =>
      api.get('/patches/', { params: { status: statusFilter || undefined, page, per_page: 20 } })
        .then((r) => r.data),
    placeholderData: (prev) => prev,
  });

  const approve = useMutation({
    mutationFn: (patch_ids: string[]) => api.post('/patches/approve', { patch_ids }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['patches'] });
      qc.invalidateQueries({ queryKey: ['patch-summary'] });
      setSelected(new Set());
    },
  });

  const patches = data?.items ?? [];
  const totalPages = data?.pages ?? 1;

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) { next.delete(id); } else { next.add(id); }
      return next;
    });
  };

  const toggleAll = () => {
    if (selected.size === patches.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(patches.map((p) => p.id)));
    }
  };

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">OS Patches</h1>
          <p className="text-sm text-gray-500">Windows Update management</p>
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

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-3 gap-4">
          <div className="bg-white border border-gray-100 rounded-xl p-4 shadow-xs">
            <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">Pending</p>
            <p className="text-2xl font-bold text-amber-600 mt-1">{summary.total_pending}</p>
          </div>
          <div className="bg-white border border-gray-100 rounded-xl p-4 shadow-xs">
            <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">Installed</p>
            <p className="text-2xl font-bold text-green-600 mt-1">{summary.total_installed}</p>
          </div>
          <div className="bg-white border border-gray-100 rounded-xl p-4 shadow-xs">
            <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">Failed</p>
            <p className="text-2xl font-bold text-red-600 mt-1">{summary.total_failed}</p>
          </div>
        </div>
      )}

      {/* Filter + action bar */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex gap-1 bg-gray-100 p-1 rounded-lg">
          {['pending', 'approved', 'installed', 'failed', ''].map((s) => (
            <button
              key={s || 'all'}
              onClick={() => { setStatusFilter(s); setPage(1); setSelected(new Set()); }}
              className={`px-3 py-1.5 text-xs font-semibold rounded-md transition ${
                statusFilter === s ? 'bg-white text-gray-800 shadow-xs' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {s || 'All'}
            </button>
          ))}
        </div>
        {selected.size > 0 && (
          <button
            onClick={() => approve.mutate(Array.from(selected))}
            disabled={approve.isPending}
            className="flex items-center gap-2 px-4 py-2 bg-brand-500 text-white text-sm font-semibold rounded-lg hover:bg-brand-600 disabled:opacity-60 transition"
          >
            <CheckCircle size={15} />
            Approve {selected.size} selected
          </button>
        )}
      </div>

      <div className="bg-white rounded-xl border border-gray-100 shadow-xs overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50">
              <th className="px-4 py-3 w-10">
                <input
                  type="checkbox"
                  checked={patches.length > 0 && selected.size === patches.length}
                  onChange={toggleAll}
                  className="rounded-sm border-gray-300 text-brand-500 focus:ring-brand-400"
                />
              </th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Title</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Device</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Severity</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Status</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">KB</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Discovered</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {isLoading
              ? Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i}>
                    {Array.from({ length: 7 }).map((_, j) => (
                      <td key={j} className="px-4 py-3">
                        <div className="h-4 bg-gray-100 rounded-sm animate-pulse" />
                      </td>
                    ))}
                  </tr>
                ))
              : patches.map((p) => (
                  <tr key={p.id} className={`hover:bg-gray-50 transition-colors ${selected.has(p.id) ? 'bg-brand-50/40' : ''}`}>
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        checked={selected.has(p.id)}
                        onChange={() => toggleSelect(p.id)}
                        className="rounded-sm border-gray-300 text-brand-500 focus:ring-brand-400"
                      />
                    </td>
                    <td className="px-4 py-3 font-medium text-gray-800 max-w-xs truncate">{p.title}</td>
                    <td className="px-4 py-3 text-gray-500 text-xs font-mono">{p.device_hostname ?? p.device_id.slice(0, 8)}</td>
                    <td className="px-4 py-3">
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${SEV_BADGE[p.severity?.toLowerCase()] ?? SEV_BADGE.unspecified}`}>
                        {p.severity ?? 'Unknown'}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${STATUS_BADGE[p.status] ?? ''}`}>
                        {p.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-400 font-mono">{p.kb_article ?? '—'}</td>
                    <td className="px-4 py-3 text-xs text-gray-400">
                      {new Date(p.discovered_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
          </tbody>
        </table>

        {!isLoading && patches.length === 0 && (
          <div className="py-16 text-center text-gray-400">
            <Shield size={32} className="mx-auto mb-3 text-gray-200" />
            <p className="text-sm">No {statusFilter || ''} patches.</p>
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
