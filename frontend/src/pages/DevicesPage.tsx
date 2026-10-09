import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Search, Monitor, Wifi, WifiOff, RefreshCw } from 'lucide-react';
import api from '../api/client';
import type { Device, PaginatedResponse } from '../api/types';

const STATUS_BADGE: Record<string, string> = {
  healthy:  'bg-green-100 text-green-700',
  warning:  'bg-amber-100 text-amber-700',
  critical: 'bg-red-100 text-red-600',
  offline:  'bg-gray-100 text-gray-500',
  unknown:  'bg-gray-100 text-gray-400',
};

const PLATFORM_ICON = (platform: string) => {
  if (platform === 'windows') return '🪟';
  if (platform === 'macos')   return '🍎';
  if (platform === 'linux')   return '🐧';
  return '📱';
};

function fetchDevices(page: number, search: string): Promise<PaginatedResponse<Device>> {
  return api.get('/devices/', { params: { page, per_page: 20, search: search || undefined, include_metrics: true } })
    .then((r) => r.data);
}

export default function DevicesPage() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');

  // Simple debounce via timeout
  const handleSearch = (val: string) => {
    setSearch(val);
    clearTimeout((window as any)._searchTimer);
    (window as any)._searchTimer = setTimeout(() => {
      setDebouncedSearch(val);
      setPage(1);
    }, 300);
  };

  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['devices', page, debouncedSearch],
    queryFn: () => fetchDevices(page, debouncedSearch),
    placeholderData: (prev) => prev,
  });

  const devices = data?.items ?? [];
  const totalPages = data?.pages ?? 1;

  return (
    <div className="p-6 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Devices</h1>
          <p className="text-sm text-gray-500">{data?.total ?? '—'} total</p>
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

      {/* Search */}
      <div className="relative max-w-sm">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
        <input
          type="text"
          placeholder="Search devices…"
          value={search}
          onChange={(e) => handleSearch(e.target.value)}
          className="w-full pl-9 pr-3 py-2 text-sm border border-gray-200 rounded-lg bg-white focus:outline-hidden focus:ring-2 focus:ring-brand-400 transition"
        />
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-xs overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50">
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Device</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">OS</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">IP</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">CPU</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">RAM</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Status</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Last Seen</th>
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
              : devices.map((d) => (
                  <tr key={d.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        {d.is_online
                          ? <Wifi size={14} className="text-green-500 shrink-0" />
                          : <WifiOff size={14} className="text-gray-300 shrink-0" />}
                        <span className="font-medium text-gray-800 truncate max-w-[160px]">
                          {d.display_name || d.hostname}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      {PLATFORM_ICON(d.platform)} {d.os_name ?? d.platform}
                    </td>
                    <td className="px-4 py-3 text-gray-500 font-mono text-xs">{d.ip_address ?? '—'}</td>
                    <td className="px-4 py-3 text-gray-500">
                      {d.latest_metrics?.cpu_pct != null ? `${d.latest_metrics.cpu_pct.toFixed(0)}%` : '—'}
                    </td>
                    <td className="px-4 py-3 text-gray-500">
                      {d.latest_metrics?.ram_pct != null ? `${d.latest_metrics.ram_pct.toFixed(0)}%` : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${STATUS_BADGE[d.status] ?? STATUS_BADGE.unknown}`}>
                        {d.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-400 text-xs">
                      {d.last_seen ? new Date(d.last_seen).toLocaleString() : '—'}
                    </td>
                  </tr>
                ))}
          </tbody>
        </table>

        {!isLoading && devices.length === 0 && (
          <div className="py-16 text-center text-gray-400">
            <Monitor size={32} className="mx-auto mb-3 text-gray-200" />
            <p className="text-sm">No devices found{debouncedSearch ? ` matching "${debouncedSearch}"` : ''}.</p>
          </div>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-sm text-gray-500">
          <span>Page {page} of {totalPages}</span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-3 py-1.5 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40 transition"
            >
              Previous
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="px-3 py-1.5 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40 transition"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
