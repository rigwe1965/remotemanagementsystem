import { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { HardDrive } from 'lucide-react';
import api from '../api/client';
import type { Device } from '../api/types';
import { apiErrorMessage } from '../api/errors';

interface DiskInfo {
  mountpoint?: string;
  device?: string;
  total_gb?: number;
  used_gb?: number;
  free_gb?: number;
  percent?: number;
}

interface DeviceWithDisks extends Device {
  latest_metrics?: {
    cpu_pct: number | null;
    ram_pct: number | null;
    disk_pct: number | null;
    uptime_seconds: number | null;
    collected_at: string;
    disks?: DiskInfo[];
  } | null;
}

const TASK_ACTIONS = [
  { key: 'defrag',     label: 'Defragment',       desc: 'Defrag all NTFS volumes' },
  { key: 'check_disk', label: 'Check Disk',        desc: 'Run chkdsk on all volumes' },
  { key: 'clean_temp', label: 'Clean Temp Files',  desc: 'Delete temp files and caches' },
];

function DiskBar({ pct }: { pct: number }) {
  const color = pct < 75 ? 'bg-green-500' : pct < 90 ? 'bg-amber-400' : 'bg-red-500';
  return (
    <div className="w-full bg-gray-100 rounded-full h-2">
      <div className={`${color} h-2 rounded-full transition-all`} style={{ width: `${Math.min(pct, 100)}%` }} />
    </div>
  );
}

export default function DiskManagementPage() {
  const [selectedDevice, setSelectedDevice] = useState('');
  const [taskMsg, setTaskMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);

  const { data: devicesData } = useQuery<{ items: DeviceWithDisks[] }>({
    queryKey: ['devices-disk'],
    queryFn: () =>
      api.get('/devices/', { params: { per_page: 100, include_metrics: true } }).then((r) => r.data),
  });

  const devices = (devicesData?.items ?? []).filter((d) => !d.is_agentless);
  const selected = devices.find((d) => d.id === selectedDevice);
  const disks: DiskInfo[] = selected?.latest_metrics?.disks ?? [];

  const queueTask = useMutation({
    mutationFn: ({ device_id, task_type }: { device_id: string; task_type: string }) =>
      api.post(`/devices/${device_id}/queue_task`, { task_type }),
    onSuccess: (_, vars) => {
      setTaskMsg({ type: 'ok', text: `${vars.task_type} queued — agent will execute on next poll.` });
    },
    onError: (e: unknown) => {
      setTaskMsg({ type: 'err', text: apiErrorMessage(e, 'Failed to queue task') });
    },
  });

  return (
    <div className="p-6 space-y-5">
      <div>
        <h1 className="text-xl font-bold text-gray-900">Disk Management</h1>
        <p className="text-sm text-gray-500">Disk health, usage, and maintenance actions</p>
      </div>

      <div className="w-64">
        <label className="text-xs font-medium text-gray-600 block mb-1">Device</label>
        <select
          value={selectedDevice}
          onChange={(e) => { setSelectedDevice(e.target.value); setTaskMsg(null); }}
          className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-brand-400 bg-white"
        >
          <option value="">Select a device…</option>
          {devices.map((d) => (
            <option key={d.id} value={d.id}>
              {d.display_name || d.hostname} {d.is_online ? '●' : '○'}
            </option>
          ))}
        </select>
      </div>

      {!selectedDevice ? (
        <div className="py-20 text-center text-gray-400">
          <HardDrive size={40} className="mx-auto mb-3 text-gray-200" />
          <p className="text-sm">Select a device to view disk information.</p>
        </div>
      ) : (
        <>
          {/* Disk usage cards */}
          {disks.length === 0 ? (
            <div className="py-12 text-center text-gray-400 bg-white border border-gray-100 rounded-xl">
              <HardDrive size={28} className="mx-auto mb-2 text-gray-200" />
              <p className="text-sm">No disk metrics available — agent may be offline.</p>
            </div>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {disks.slice(0, 4).map((disk, i) => {
                const pct = disk.percent ?? 0;
                const mount = disk.mountpoint || disk.device || `Disk ${i + 1}`;
                const health = pct < 75 ? 'Healthy' : pct < 90 ? 'Warning' : 'Critical';
                const healthColor = pct < 75 ? 'text-green-600' : pct < 90 ? 'text-amber-600' : 'text-red-600';
                return (
                  <div key={i} className="bg-white border border-gray-100 rounded-xl p-4 shadow-xs space-y-3">
                    <div className="flex items-center justify-between">
                      <p className="font-semibold text-gray-800 text-sm truncate">{mount}</p>
                      <span className={`text-xs font-bold ${healthColor}`}>{health}</span>
                    </div>
                    <div>
                      <div className="flex justify-between text-xs text-gray-500 mb-1.5">
                        <span>{pct.toFixed(1)}% used</span>
                        <span>{(disk.free_gb ?? 0).toFixed(1)} GB free</span>
                      </div>
                      <DiskBar pct={pct} />
                    </div>
                    <div className="grid grid-cols-2 gap-1 text-xs text-gray-500">
                      <div>Used: <span className="font-medium text-gray-700">{(disk.used_gb ?? 0).toFixed(1)} GB</span></div>
                      <div>Total: <span className="font-medium text-gray-700">{(disk.total_gb ?? 0).toFixed(1)} GB</span></div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Maintenance actions */}
          <div className="bg-white border border-gray-100 rounded-xl p-5 shadow-xs">
            <h2 className="text-sm font-bold text-gray-800 mb-4">Maintenance Actions</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {TASK_ACTIONS.map((action) => (
                <button
                  key={action.key}
                  onClick={() => queueTask.mutate({ device_id: selectedDevice, task_type: action.key })}
                  disabled={!selected?.is_online || queueTask.isPending}
                  className="flex flex-col items-start p-4 border border-gray-200 rounded-xl hover:border-brand-300 hover:bg-brand-50/30 disabled:opacity-50 disabled:cursor-not-allowed transition text-left group"
                >
                  <p className="text-sm font-semibold text-gray-800 group-hover:text-brand-700">{action.label}</p>
                  <p className="text-xs text-gray-400 mt-1">{action.desc}</p>
                  {!selected?.is_online && (
                    <span className="text-[10px] text-red-400 mt-2 font-medium">Device offline</span>
                  )}
                </button>
              ))}
            </div>
            {taskMsg && (
              <p className={`mt-3 text-xs font-medium ${taskMsg.type === 'ok' ? 'text-green-600' : 'text-red-600'}`}>
                {taskMsg.text}
              </p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
