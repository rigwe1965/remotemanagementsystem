import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Package, Search, RefreshCw } from 'lucide-react';
import api from '../api/client';
import type { Device } from '../api/types';

interface SoftwareItem {
  name: string;
  version?: string;
  publisher?: string;
  install_date?: string;
}

export default function SoftwarePatchesPage() {
  const [selectedDevice, setSelectedDevice] = useState<string>('');
  const [search, setSearch] = useState('');

  const { data: devicesData } = useQuery<{ items: Device[] }>({
    queryKey: ['devices-online'],
    queryFn: () =>
      api.get('/devices/', { params: { per_page: 100, is_agentless: false } }).then((r) => r.data),
  });

  const agentDevices = (devicesData?.items ?? []).filter((d) => !d.is_agentless);

  const { data: software, isLoading, isFetching, refetch } = useQuery<SoftwareItem[]>({
    queryKey: ['software', selectedDevice],
    queryFn: () =>
      api.get(`/devices/${selectedDevice}/software`).then((r) => r.data.software ?? r.data),
    enabled: !!selectedDevice,
    staleTime: 60_000,
  });

  const filtered = (software ?? []).filter((s) =>
    !search || s.name.toLowerCase().includes(search.toLowerCase()) ||
    (s.publisher ?? '').toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Software Inventory</h1>
          <p className="text-sm text-gray-500">Installed software on managed devices</p>
        </div>
        {selectedDevice && (
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="flex items-center gap-2 text-sm text-gray-500 hover:text-brand-600 transition disabled:opacity-50"
          >
            <RefreshCw size={15} className={isFetching ? 'animate-spin' : ''} />
            Refresh
          </button>
        )}
      </div>

      <div className="flex flex-wrap gap-3">
        <div className="w-64">
          <label className="text-xs font-medium text-gray-600 block mb-1">Device</label>
          <select
            value={selectedDevice}
            onChange={(e) => setSelectedDevice(e.target.value)}
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-brand-400 bg-white"
          >
            <option value="">Select a device…</option>
            {agentDevices.map((d) => (
              <option key={d.id} value={d.id}>
                {d.display_name || d.hostname}
                {d.is_online ? ' ●' : ' ○'}
              </option>
            ))}
          </select>
        </div>

        {selectedDevice && (
          <div className="relative self-end">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search software…"
              className="pl-8 pr-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-brand-400"
            />
          </div>
        )}
      </div>

      {!selectedDevice ? (
        <div className="py-20 text-center text-gray-400">
          <Package size={40} className="mx-auto mb-3 text-gray-200" />
          <p className="text-sm">Select a device to view installed software.</p>
          <p className="text-xs mt-1 text-gray-300">Agentless devices not shown — no agent to report inventory.</p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-100 shadow-xs overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100 bg-gray-50 flex items-center justify-between">
            <p className="text-xs font-semibold text-gray-500">
              {isLoading ? 'Loading…' : `${filtered.length} item${filtered.length !== 1 ? 's' : ''}`}
            </p>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100">
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Name</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Version</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Publisher</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Installed</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {isLoading
                ? Array.from({ length: 10 }).map((_, i) => (
                    <tr key={i}>
                      {Array.from({ length: 4 }).map((_, j) => (
                        <td key={j} className="px-4 py-3">
                          <div className="h-4 bg-gray-100 rounded-sm animate-pulse" />
                        </td>
                      ))}
                    </tr>
                  ))
                : filtered.map((s, i) => (
                    <tr key={i} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-2.5 font-medium text-gray-800">{s.name}</td>
                      <td className="px-4 py-2.5 text-gray-500 font-mono text-xs">{s.version ?? '—'}</td>
                      <td className="px-4 py-2.5 text-gray-400 text-xs">{s.publisher ?? '—'}</td>
                      <td className="px-4 py-2.5 text-gray-400 text-xs">{s.install_date ?? '—'}</td>
                    </tr>
                  ))}
            </tbody>
          </table>
          {!isLoading && filtered.length === 0 && (
            <div className="py-12 text-center text-gray-400">
              <Package size={28} className="mx-auto mb-2 text-gray-200" />
              <p className="text-sm">{search ? `No matches for "${search}"` : 'No software data available.'}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
