import { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { Wrench, Power, RotateCcw, Trash2, Globe, HardDrive, Shield } from 'lucide-react';
import api from '../api/client';
import type { Device, DeviceMetrics } from '../api/types';
import { apiErrorMessage } from '../api/errors';

const ACTIONS = [
  { key: 'clean_temp',    label: 'Clean Temp Files',      icon: Trash2,    color: 'text-amber-500',  desc: 'Delete temp files and system caches' },
  { key: 'clear_browser', label: 'Clear Browser History', icon: Globe,     color: 'text-blue-500',   desc: 'Clear browser history and cookies' },
  { key: 'defrag',        label: 'Defragment Disks',      icon: HardDrive, color: 'text-purple-500', desc: 'Defragment all NTFS volumes' },
  { key: 'check_disk',    label: 'Check Disk',            icon: HardDrive, color: 'text-orange-500', desc: 'Run chkdsk on all volumes' },
  { key: 'restore_point', label: 'Create Restore Point',  icon: Shield,    color: 'text-green-500',  desc: 'Create a Windows system restore point' },
  { key: 'reboot',        label: 'Reboot Device',         icon: RotateCcw, color: 'text-amber-600',  desc: 'Gracefully reboot the device' },
  { key: 'shutdown',      label: 'Shutdown Device',       icon: Power,     color: 'text-red-500',    desc: 'Shutdown the device immediately', danger: true },
];

function fmtUptime(sec?: number | null) {
  if (!sec) return '—';
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return [d && `${d}d`, h && `${h}h`, m && `${m}m`].filter(Boolean).join(' ') || '< 1m';
}

export default function MaintenancePage() {
  const [selectedDevice, setSelectedDevice] = useState('');
  const [msgs, setMsgs] = useState<Record<string, { type: 'ok' | 'err'; text: string }>>({});

  const { data: devicesData } = useQuery<{ items: Device[] }>({
    queryKey: ['devices-maint'],
    queryFn: () =>
      api.get('/devices/', { params: { per_page: 100, include_metrics: true } }).then((r) => r.data),
  });

  const onlineDevices = (devicesData?.items ?? []).filter((d) => d.is_online && !d.is_agentless);
  const selected = onlineDevices.find((d) => d.id === selectedDevice);
  const metrics = selected?.latest_metrics as (DeviceMetrics & { disks?: any[] }) | null | undefined;

  const queueTask = useMutation({
    mutationFn: ({ task_type }: { task_type: string }) =>
      api.post(`/devices/${selectedDevice}/queue_task`, { task_type }),
    onSuccess: (_, vars) => {
      setMsgs((prev) => ({ ...prev, [vars.task_type]: { type: 'ok', text: 'Queued — agent executes on next poll.' } }));
    },
    onError: (e: unknown, vars) => {
      setMsgs((prev) => ({
        ...prev,
        [vars.task_type]: { type: 'err', text: apiErrorMessage(e, 'Failed') },
      }));
    },
  });

  const handleAction = (key: string, danger?: boolean) => {
    if (danger && !confirm(`This will ${key} the device. Continue?`)) return;
    setMsgs((prev) => { const n = { ...prev }; delete n[key]; return n; });
    queueTask.mutate({ task_type: key });
  };

  return (
    <div className="p-6 space-y-5">
      <div>
        <h1 className="text-xl font-bold text-gray-900">Maintenance</h1>
        <p className="text-sm text-gray-500">Remote maintenance actions on online devices</p>
      </div>

      <div className="w-72">
        <label className="text-xs font-medium text-gray-600 block mb-1">Online Device</label>
        <select
          value={selectedDevice}
          onChange={(e) => { setSelectedDevice(e.target.value); setMsgs({}); }}
          className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-brand-400 bg-white"
        >
          <option value="">Select an online device…</option>
          {onlineDevices.map((d) => (
            <option key={d.id} value={d.id}>
              {d.display_name || d.hostname} — {d.ip_address ?? '—'}
            </option>
          ))}
        </select>
        {(devicesData?.items ?? []).length > 0 && onlineDevices.length === 0 && (
          <p className="text-xs text-amber-600 mt-1">No online agent-managed devices.</p>
        )}
      </div>

      {!selectedDevice ? (
        <div className="py-20 text-center text-gray-400">
          <Wrench size={40} className="mx-auto mb-3 text-gray-200" />
          <p className="text-sm">Select an online device to perform maintenance.</p>
        </div>
      ) : (
        <>
          {/* Device info */}
          {selected && (
            <div className="bg-white border border-gray-100 rounded-xl p-4 shadow-xs">
              <div className="flex items-center gap-3 mb-3">
                <div className="w-2.5 h-2.5 rounded-full bg-green-500 shadow-[0_0_6px_#22c55e88]" />
                <span className="font-bold text-gray-900">{selected.hostname}</span>
                <span className="text-sm text-gray-400">{selected.ip_address ?? '—'}</span>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs text-gray-500">
                <div>OS<br /><span className="font-semibold text-gray-700">{selected.os_name ?? '—'}</span></div>
                <div>Platform<br /><span className="font-semibold text-gray-700 capitalize">{selected.platform}</span></div>
                <div>Uptime<br /><span className="font-semibold text-gray-700">{fmtUptime(metrics?.uptime_seconds)}</span></div>
                <div>CPU / RAM<br /><span className="font-semibold text-gray-700">
                  {metrics?.cpu_pct != null ? `${metrics.cpu_pct.toFixed(0)}%` : '—'} /
                  {metrics?.ram_pct != null ? ` ${metrics.ram_pct.toFixed(0)}%` : ' —'}
                </span></div>
              </div>
            </div>
          )}

          {/* Action grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {ACTIONS.map((action) => {
              const Icon = action.icon;
              const msg = msgs[action.key];
              return (
                <div key={action.key} className={`bg-white border rounded-xl p-4 shadow-xs ${action.danger ? 'border-red-100' : 'border-gray-100'}`}>
                  <div className="flex items-start gap-3">
                    <div className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${action.danger ? 'bg-red-50' : 'bg-gray-50'}`}>
                      <Icon size={16} className={action.color} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold text-gray-800">{action.label}</p>
                      <p className="text-xs text-gray-400 mt-0.5">{action.desc}</p>
                      {msg && (
                        <p className={`text-[11px] font-medium mt-1.5 ${msg.type === 'ok' ? 'text-green-600' : 'text-red-600'}`}>
                          {msg.text}
                        </p>
                      )}
                    </div>
                  </div>
                  <button
                    onClick={() => handleAction(action.key, action.danger)}
                    disabled={queueTask.isPending}
                    className={`mt-3 w-full py-1.5 text-xs font-semibold rounded-lg transition disabled:opacity-50 ${
                      action.danger
                        ? 'bg-red-50 text-red-600 hover:bg-red-100 border border-red-200'
                        : 'bg-brand-500 text-white hover:bg-brand-600'
                    }`}
                  >
                    Run
                  </button>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
