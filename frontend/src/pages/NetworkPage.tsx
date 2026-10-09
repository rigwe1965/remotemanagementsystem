import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Network, Play, RefreshCw, Wifi, WifiOff } from 'lucide-react';
import api from '../api/client';

interface NetworkScan {
  id: string;
  subnet: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  hosts_found: number;
  started_at?: string;
  completed_at?: string;
}

interface DiscoveredHost {
  ip: string;
  hostname?: string;
  mac?: string;
  vendor?: string;
  platform?: string;
  device_type?: string;
  is_online: boolean;
}

const SCAN_STATUS: Record<string, string> = {
  pending:   'bg-gray-100 text-gray-500',
  running:   'bg-blue-100 text-blue-600',
  completed: 'bg-green-100 text-green-700',
  failed:    'bg-red-100 text-red-600',
};

export default function NetworkPage() {
  const [subnet, setSubnet] = useState('192.168.1.0/24');
  const [activeScan, setActiveScan] = useState<string | null>(null);
  const qc = useQueryClient();

  const { data: scans, isLoading: scansLoading, refetch: refetchScans } = useQuery<{ items: NetworkScan[] }>({
    queryKey: ['network-scans'],
    queryFn: () => api.get('/network/scans').then((r) => r.data),
    refetchInterval: activeScan ? 3000 : false,
  });

  const { data: scanDetail } = useQuery<{ discovered_hosts: DiscoveredHost[] }>({
    queryKey: ['network-scan', activeScan],
    queryFn: () => api.get(`/network/scans/${activeScan}`).then((r) => r.data),
    enabled: !!activeScan,
    refetchInterval: 3000,
  });

  const triggerScan = useMutation({
    mutationFn: (s: string) => api.post('/network/scan', { subnet: s }),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['network-scans'] });
      setActiveScan(res.data.scan_id ?? res.data.id);
    },
  });

  const currentScan = scans?.items.find((s) => s.id === activeScan);
  const hosts = scanDetail?.discovered_hosts ?? [];

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Network Discovery</h1>
          <p className="text-sm text-gray-500">Scan subnets for agentless devices</p>
        </div>
        <button onClick={() => refetchScans()}
          className="flex items-center gap-2 text-sm text-gray-500 hover:text-brand-600 transition">
          <RefreshCw size={14} />
          Refresh
        </button>
      </div>

      {/* Scan trigger */}
      <div className="bg-white border border-gray-100 rounded-xl p-5 shadow-xs">
        <h2 className="text-sm font-bold text-gray-800 mb-3">Start New Scan</h2>
        <div className="flex gap-3">
          <input
            type="text"
            value={subnet}
            onChange={(e) => setSubnet(e.target.value)}
            placeholder="e.g. 192.168.1.0/24"
            className="flex-1 max-w-sm px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-brand-400"
          />
          <button
            onClick={() => triggerScan.mutate(subnet)}
            disabled={!subnet || triggerScan.isPending}
            className="flex items-center gap-2 px-4 py-2 bg-brand-500 text-white text-sm font-semibold rounded-lg hover:bg-brand-600 disabled:opacity-50 transition"
          >
            <Play size={14} />
            {triggerScan.isPending ? 'Starting…' : 'Scan'}
          </button>
        </div>
      </div>

      {/* Active scan results */}
      {activeScan && (
        <div className="bg-white border border-gray-100 rounded-xl p-5 shadow-xs space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-bold text-gray-800">Scan Results</h2>
              {currentScan && (
                <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${SCAN_STATUS[currentScan.status]}`}>
                  {currentScan.status}
                </span>
              )}
            </div>
            {currentScan?.status === 'running' && (
              <div className="flex items-center gap-1.5 text-xs text-blue-600">
                <RefreshCw size={12} className="animate-spin" />
                Scanning…
              </div>
            )}
          </div>

          {hosts.length > 0 ? (
            <div className="overflow-hidden rounded-lg border border-gray-100">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-100">
                    <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-2.5">Status</th>
                    <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-2.5">IP</th>
                    <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-2.5">Hostname</th>
                    <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-2.5">MAC / Vendor</th>
                    <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-2.5">Platform</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {hosts.map((h) => (
                    <tr key={h.ip} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-2.5">
                        {h.is_online
                          ? <Wifi size={14} className="text-green-500" />
                          : <WifiOff size={14} className="text-gray-300" />}
                      </td>
                      <td className="px-4 py-2.5 font-mono text-xs text-gray-700">{h.ip}</td>
                      <td className="px-4 py-2.5 text-gray-600 text-xs">{h.hostname ?? '—'}</td>
                      <td className="px-4 py-2.5 text-xs text-gray-400">
                        {h.mac ? (
                          <span>{h.mac}{h.vendor ? ` · ${h.vendor}` : ''}</span>
                        ) : '—'}
                      </td>
                      <td className="px-4 py-2.5 text-xs text-gray-500 capitalize">{h.platform ?? h.device_type ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : currentScan?.status === 'running' ? (
            <p className="text-sm text-gray-400 text-center py-8">Scan in progress…</p>
          ) : (
            <p className="text-sm text-gray-400 text-center py-8">No hosts discovered.</p>
          )}
        </div>
      )}

      {/* Scan history */}
      <div>
        <h2 className="text-sm font-bold text-gray-700 mb-3">Scan History</h2>
        <div className="bg-white rounded-xl border border-gray-100 shadow-xs overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Subnet</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Status</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Hosts</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Started</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {scansLoading
                ? Array.from({ length: 3 }).map((_, i) => (
                    <tr key={i}>
                      {Array.from({ length: 5 }).map((_, j) => (
                        <td key={j} className="px-4 py-3">
                          <div className="h-4 bg-gray-100 rounded-sm animate-pulse" />
                        </td>
                      ))}
                    </tr>
                  ))
                : (scans?.items ?? []).map((s) => (
                    <tr key={s.id} className={`hover:bg-gray-50 transition-colors ${activeScan === s.id ? 'bg-brand-50/30' : ''}`}>
                      <td className="px-4 py-3 font-mono text-xs text-gray-700">{s.subnet}</td>
                      <td className="px-4 py-3">
                        <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${SCAN_STATUS[s.status]}`}>
                          {s.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-gray-600">{s.hosts_found ?? '—'}</td>
                      <td className="px-4 py-3 text-xs text-gray-400">
                        {s.started_at ? new Date(s.started_at).toLocaleString() : '—'}
                      </td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => setActiveScan(s.id)}
                          className="text-xs text-brand-600 hover:text-brand-700 font-semibold transition"
                        >
                          View
                        </button>
                      </td>
                    </tr>
                  ))}
            </tbody>
          </table>
          {!scansLoading && (scans?.items ?? []).length === 0 && (
            <div className="py-12 text-center text-gray-400">
              <Network size={32} className="mx-auto mb-3 text-gray-200" />
              <p className="text-sm">No scans run yet.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
