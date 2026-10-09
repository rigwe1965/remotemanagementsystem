import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Zap, Play, RefreshCw, Clock } from 'lucide-react';
import api from '../api/client';

interface AutomationProfile {
  id: string;
  name: string;
  description?: string;
  trigger_type: string;
  schedule?: string;
  is_active: boolean;
  action_type: string;
  customer_id?: string;
  last_run_at?: string;
  run_count: number;
  created_at: string;
}

interface AutomationRun {
  id: string;
  profile_id: string;
  profile_name?: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  started_at?: string;
  completed_at?: string;
  message?: string;
}

const RUN_STATUS: Record<string, string> = {
  queued:    'bg-gray-100 text-gray-500',
  running:   'bg-blue-100 text-blue-600',
  completed: 'bg-green-100 text-green-700',
  failed:    'bg-red-100 text-red-600',
};

export default function AutomationPage() {
  const [tab, setTab] = useState<'profiles' | 'runs'>('profiles');
  const qc = useQueryClient();

  const { data: profiles, isLoading: profilesLoading, refetch: refetchProfiles } = useQuery<{ items: AutomationProfile[] }>({
    queryKey: ['automation-profiles'],
    queryFn: () => api.get('/automation/profiles').then((r) => r.data),
  });

  const { data: runs, isLoading: runsLoading, refetch: refetchRuns } = useQuery<{ items: AutomationRun[] }>({
    queryKey: ['automation-runs'],
    queryFn: () => api.get('/automation/runs').then((r) => r.data),
    refetchInterval: tab === 'runs' ? 5000 : false,
  });

  const runNow = useMutation({
    mutationFn: (id: string) => api.post(`/automation/profiles/${id}/run`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['automation-runs'] });
      qc.invalidateQueries({ queryKey: ['automation-profiles'] });
      setTab('runs');
    },
  });

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Automation</h1>
          <p className="text-sm text-gray-500">Scheduled tasks and maintenance profiles</p>
        </div>
      </div>

      <div className="flex gap-1 bg-gray-100 p-1 rounded-lg w-fit">
        {(['profiles', 'runs'] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-1.5 text-xs font-semibold rounded-md transition capitalize ${
              tab === t ? 'bg-white text-gray-800 shadow-xs' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {t === 'profiles' ? 'Profiles' : 'Run History'}
          </button>
        ))}
      </div>

      {tab === 'profiles' && (
        <div className="space-y-3">
          <div className="flex justify-end">
            <button onClick={() => refetchProfiles()}
              className="flex items-center gap-2 text-sm text-gray-500 hover:text-brand-600 transition">
              <RefreshCw size={14} />
              Refresh
            </button>
          </div>
          {profilesLoading
            ? Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="h-20 bg-white border border-gray-100 rounded-xl animate-pulse" />
              ))
            : (profiles?.items ?? []).map((p) => (
                <div key={p.id} className="bg-white border border-gray-100 rounded-xl p-4 shadow-xs">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex items-start gap-3 min-w-0">
                      <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${
                        p.is_active ? 'bg-brand-500' : 'bg-gray-200'
                      }`}>
                        <Zap size={14} className={p.is_active ? 'text-white' : 'text-gray-400'} />
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <p className="font-semibold text-gray-800 text-sm">{p.name}</p>
                          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${
                            p.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-400'
                          }`}>
                            {p.is_active ? 'ACTIVE' : 'INACTIVE'}
                          </span>
                          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded-sm bg-gray-100 text-gray-500">{p.trigger_type}</span>
                        </div>
                        {p.description && <p className="text-xs text-gray-400 mt-0.5">{p.description}</p>}
                        <div className="flex items-center gap-3 mt-1.5 text-[11px] text-gray-400">
                          {p.schedule && <span><Clock size={10} className="inline mr-0.5" />{p.schedule}</span>}
                          <span>{p.run_count} run{p.run_count !== 1 ? 's' : ''}</span>
                          {p.last_run_at && <span>Last: {new Date(p.last_run_at).toLocaleDateString()}</span>}
                        </div>
                      </div>
                    </div>
                    <button
                      onClick={() => runNow.mutate(p.id)}
                      disabled={!p.is_active || runNow.isPending}
                      className="flex items-center gap-2 px-3 py-1.5 bg-brand-500 text-white text-xs font-semibold rounded-lg hover:bg-brand-600 disabled:opacity-50 transition shrink-0"
                    >
                      <Play size={12} />
                      Run Now
                    </button>
                  </div>
                </div>
              ))}
          {!profilesLoading && (profiles?.items ?? []).length === 0 && (
            <div className="py-16 text-center text-gray-400">
              <Zap size={32} className="mx-auto mb-3 text-gray-200" />
              <p className="text-sm">No automation profiles configured.</p>
            </div>
          )}
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
          <div className="bg-white rounded-xl border border-gray-100 shadow-xs overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50">
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Profile</th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Status</th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Started</th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Completed</th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Message</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {runsLoading
                  ? Array.from({ length: 5 }).map((_, i) => (
                      <tr key={i}>
                        {Array.from({ length: 5 }).map((_, j) => (
                          <td key={j} className="px-4 py-3">
                            <div className="h-4 bg-gray-100 rounded-sm animate-pulse" />
                          </td>
                        ))}
                      </tr>
                    ))
                  : (runs?.items ?? []).map((r) => (
                      <tr key={r.id} className="hover:bg-gray-50 transition-colors">
                        <td className="px-4 py-3 font-medium text-gray-800">{r.profile_name ?? '—'}</td>
                        <td className="px-4 py-3">
                          <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${RUN_STATUS[r.status]}`}>
                            {r.status}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-xs text-gray-400">
                          {r.started_at ? new Date(r.started_at).toLocaleString() : '—'}
                        </td>
                        <td className="px-4 py-3 text-xs text-gray-400">
                          {r.completed_at ? new Date(r.completed_at).toLocaleString() : '—'}
                        </td>
                        <td className="px-4 py-3 text-xs text-gray-500 max-w-xs truncate">{r.message ?? '—'}</td>
                      </tr>
                    ))}
              </tbody>
            </table>
            {!runsLoading && (runs?.items ?? []).length === 0 && (
              <div className="py-12 text-center text-gray-400">
                <p className="text-sm">No automation runs yet.</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
