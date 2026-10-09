import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Terminal, Play, RefreshCw, CheckCircle, XCircle, Clock, ChevronDown, ChevronUp } from 'lucide-react';
import api from '../api/client';

interface Script {
  id: string;
  name: string;
  description?: string;
  shell: string;
  is_builtin: boolean;
  created_at: string;
}

interface ScriptRun {
  id: string;
  script_id: string;
  script_name?: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'timeout';
  device_ids: string[];
  started_at?: string;
  completed_at?: string;
  output?: string;
  error?: string;
}

interface Device { id: string; hostname: string; display_name: string; is_online: boolean }

const RUN_STATUS: Record<string, string> = {
  queued:    'bg-gray-100 text-gray-500',
  running:   'bg-blue-100 text-blue-600',
  completed: 'bg-green-100 text-green-700',
  failed:    'bg-red-100 text-red-600',
  timeout:   'bg-orange-100 text-orange-600',
};

const RUN_ICON = (status: string) => {
  if (status === 'completed') return <CheckCircle size={14} className="text-green-500" />;
  if (status === 'failed' || status === 'timeout') return <XCircle size={14} className="text-red-500" />;
  return <Clock size={14} className="text-gray-400" />;
};

export default function ScriptsPage() {
  const [runScriptId, setRunScriptId] = useState<string | null>(null);
  const [selectedDevices, setSelectedDevices] = useState<string[]>([]);
  const [expandedRun, setExpandedRun] = useState<string | null>(null);
  const [tab, setTab] = useState<'library' | 'runs'>('library');
  const qc = useQueryClient();

  const { data: scripts, isLoading: scriptsLoading } = useQuery<Script[]>({
    queryKey: ['scripts'],
    queryFn: () => api.get('/scripts/').then((r) => r.data.items ?? r.data),
  });

  const { data: devices } = useQuery<{ items: Device[] }>({
    queryKey: ['devices-list'],
    queryFn: () => api.get('/devices/', { params: { per_page: 100 } }).then((r) => r.data),
  });

  const { data: runs, isLoading: runsLoading, refetch: refetchRuns } = useQuery<{ items: ScriptRun[] }>({
    queryKey: ['script-runs'],
    queryFn: () => api.get('/scripts/runs', { params: { per_page: 30 } }).then((r) => r.data),
    refetchInterval: tab === 'runs' ? 5000 : false,
  });

  const runScript = useMutation({
    mutationFn: ({ id, device_ids }: { id: string; device_ids: string[] }) =>
      api.post(`/scripts/${id}/run`, { device_ids }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['script-runs'] });
      setRunScriptId(null);
      setSelectedDevices([]);
      setTab('runs');
    },
  });

  const onlineDevices = devices?.items.filter((d) => d.is_online) ?? [];

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Scripts</h1>
          <p className="text-sm text-gray-500">Run PowerShell/Bash scripts on managed devices</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-gray-100 p-1 rounded-lg w-fit">
        {(['library', 'runs'] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-1.5 text-xs font-semibold rounded-md transition capitalize ${
              tab === t ? 'bg-white text-gray-800 shadow-xs' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {t === 'library' ? 'Script Library' : 'Run History'}
          </button>
        ))}
      </div>

      {tab === 'library' && (
        <div className="grid gap-3">
          {scriptsLoading
            ? Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="h-16 bg-white border border-gray-100 rounded-xl animate-pulse" />
              ))
            : (scripts ?? []).map((s) => (
                <div key={s.id} className="bg-white border border-gray-100 rounded-xl p-4 shadow-xs">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex items-start gap-3 min-w-0">
                      <div className="w-8 h-8 bg-gray-900 rounded-lg flex items-center justify-center shrink-0">
                        <Terminal size={14} className="text-green-400" />
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="font-semibold text-gray-800 text-sm">{s.name}</p>
                          {s.is_builtin && (
                            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-brand-100 text-brand-600">BUILT-IN</span>
                          )}
                          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded-sm bg-gray-100 text-gray-500">{s.shell}</span>
                        </div>
                        {s.description && <p className="text-xs text-gray-400 mt-0.5 truncate">{s.description}</p>}
                      </div>
                    </div>
                    <button
                      onClick={() => { setRunScriptId(s.id); setSelectedDevices([]); }}
                      className="flex items-center gap-2 px-3 py-1.5 bg-brand-500 text-white text-xs font-semibold rounded-lg hover:bg-brand-600 transition shrink-0"
                    >
                      <Play size={12} />
                      Run
                    </button>
                  </div>

                  {/* Run modal (inline) */}
                  {runScriptId === s.id && (
                    <div className="mt-4 pt-4 border-t border-gray-100">
                      <p className="text-xs font-semibold text-gray-600 mb-2">Select online devices to target:</p>
                      {onlineDevices.length === 0 ? (
                        <p className="text-xs text-gray-400">No online devices available.</p>
                      ) : (
                        <div className="grid grid-cols-2 gap-1.5 mb-3">
                          {onlineDevices.map((d) => (
                            <label key={d.id} className="flex items-center gap-2 text-xs text-gray-700 cursor-pointer">
                              <input
                                type="checkbox"
                                checked={selectedDevices.includes(d.id)}
                                onChange={(e) => {
                                  setSelectedDevices((prev) =>
                                    e.target.checked ? [...prev, d.id] : prev.filter((id) => id !== d.id)
                                  );
                                }}
                                className="rounded-sm border-gray-300 text-brand-500 focus:ring-brand-400"
                              />
                              {d.display_name || d.hostname}
                            </label>
                          ))}
                        </div>
                      )}
                      <div className="flex gap-2">
                        <button
                          onClick={() => runScript.mutate({ id: s.id, device_ids: selectedDevices })}
                          disabled={selectedDevices.length === 0 || runScript.isPending}
                          className="px-4 py-1.5 bg-brand-500 text-white text-xs font-semibold rounded-lg hover:bg-brand-600 disabled:opacity-50 transition"
                        >
                          {runScript.isPending ? 'Running…' : `Run on ${selectedDevices.length} device${selectedDevices.length !== 1 ? 's' : ''}`}
                        </button>
                        <button
                          onClick={() => setRunScriptId(null)}
                          className="px-4 py-1.5 border border-gray-200 text-gray-600 text-xs font-semibold rounded-lg hover:bg-gray-50 transition"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              ))}
        </div>
      )}

      {tab === 'runs' && (
        <div className="space-y-3">
          <div className="flex justify-end">
            <button onClick={() => refetchRuns()}
              className="flex items-center gap-2 text-sm text-gray-500 hover:text-brand-600 transition">
              <RefreshCw size={14} />
              Refresh
            </button>
          </div>
          {runsLoading
            ? Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="h-14 bg-white border border-gray-100 rounded-xl animate-pulse" />
              ))
            : (runs?.items ?? []).map((r) => (
                <div key={r.id} className="bg-white border border-gray-100 rounded-xl shadow-xs overflow-hidden">
                  <div
                    className="flex items-center gap-3 p-4 cursor-pointer hover:bg-gray-50 transition"
                    onClick={() => setExpandedRun(expandedRun === r.id ? null : r.id)}
                  >
                    {RUN_ICON(r.status)}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold text-gray-800">{r.script_name ?? 'Script run'}</p>
                      <p className="text-xs text-gray-400">
                        {r.device_ids.length} device{r.device_ids.length !== 1 ? 's' : ''}
                        {r.started_at ? ` · ${new Date(r.started_at).toLocaleString()}` : ''}
                      </p>
                    </div>
                    <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${RUN_STATUS[r.status]}`}>
                      {r.status}
                    </span>
                    {expandedRun === r.id ? <ChevronUp size={14} className="text-gray-400" /> : <ChevronDown size={14} className="text-gray-400" />}
                  </div>
                  {expandedRun === r.id && (r.output || r.error) && (
                    <div className="px-4 pb-4">
                      <pre className={`text-xs p-3 rounded-lg font-mono whitespace-pre-wrap max-h-48 overflow-y-auto ${
                        r.error ? 'bg-red-50 text-red-700' : 'bg-gray-900 text-green-400'
                      }`}>
                        {r.error || r.output}
                      </pre>
                    </div>
                  )}
                </div>
              ))}
          {!runsLoading && (runs?.items ?? []).length === 0 && (
            <div className="py-16 text-center text-gray-400">
              <Terminal size={32} className="mx-auto mb-3 text-gray-200" />
              <p className="text-sm">No script runs yet.</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
