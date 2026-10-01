import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ShieldAlert, RefreshCw, Download, AlertTriangle } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import {
  getUsageSummary, getUsageByFeature, getUsageAlertConfig, updateUsageAlertConfig,
} from '../api/usage';
import api from '../api/client';

const RANGES: { label: string; value: string }[] = [
  { label: 'Today', value: 'today' },
  { label: '7 days', value: '7d' },
  { label: '30 days', value: '30d' },
];

function fmtCost(n: number) {
  return `$${n.toFixed(4)}`;
}

export default function UsageMonitoringPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [range, setRange] = useState('7d');

  if (user?.role !== 'superadmin' && user?.role !== 'admin') {
    return (
      <div className="p-10 text-center">
        <ShieldAlert size={40} className="mx-auto mb-3 text-red-300" />
        <p className="text-gray-700 font-semibold">Administrator access required</p>
        <p className="text-sm text-gray-400">This page is restricted to admin and superadmin accounts.</p>
      </div>
    );
  }

  const { data: summary, isLoading, refetch } = useQuery({
    queryKey: ['usage-summary', range],
    queryFn: () => getUsageSummary(range),
    refetchInterval: 45_000,
  });

  const { data: byFeature } = useQuery({
    queryKey: ['usage-by-feature', range],
    queryFn: () => getUsageByFeature(range),
  });

  const { data: alertConfig } = useQuery({
    queryKey: ['usage-alert-config'],
    queryFn: getUsageAlertConfig,
  });

  const [configDraft, setConfigDraft] = useState<{
    is_enabled: boolean; spike_multiplier: number; emails: string;
  } | null>(null);

  const cfg = configDraft ?? (alertConfig && {
    is_enabled: alertConfig.is_enabled,
    spike_multiplier: alertConfig.spike_multiplier,
    emails: (alertConfig.notification_channels.email ?? []).join(', '),
  });

  const saveConfig = useMutation({
    mutationFn: () => updateUsageAlertConfig({
      is_enabled: cfg!.is_enabled,
      spike_multiplier: cfg!.spike_multiplier,
      notification_channels: {
        ...alertConfig?.notification_channels,
        email: cfg!.emails.split(',').map((e) => e.trim()).filter(Boolean),
      },
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['usage-alert-config'] }),
  });

  const generateReport = useMutation({
    mutationFn: () => api.post('/reports/generate', { template_type: 'api_usage' }),
  });

  const totals = summary?.totals;
  const services = summary?.services ?? [];
  const anomalies = summary?.anomalies ?? [];
  const maxCalls = Math.max(1, ...services.map((s) => s.calls));

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Usage Monitoring</h1>
          <p className="text-sm text-gray-500">
            API calls, AI token consumption, and estimated cost — visible only to Super Administrators
          </p>
        </div>
        <div className="flex items-center gap-2">
          {RANGES.map((r) => (
            <button
              key={r.value}
              onClick={() => setRange(r.value)}
              className={`text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors ${
                range === r.value ? 'bg-brand-500 text-white' : 'bg-white border border-gray-200 text-gray-500 hover:bg-gray-50'
              }`}
            >
              {r.label}
            </button>
          ))}
          <button onClick={() => refetch()} className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-brand-600 px-2">
            <RefreshCw size={14} />
          </button>
        </div>
      </div>

      {anomalies.length > 0 && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 flex gap-3">
          <AlertTriangle size={18} className="text-red-500 shrink-0 mt-0.5" />
          <div className="text-sm text-red-800 space-y-1">
            <p className="font-semibold">Usage spike detected</p>
            {anomalies.map((a) => (
              <p key={a.service}>
                <b>{a.service}</b>: {a.current_hour_count} calls in the last hour
                ({a.multiplier}x the 7-day average of {a.baseline_avg})
              </p>
            ))}
          </div>
        </div>
      )}

      {/* KPI tiles */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { label: 'API Calls', value: isLoading ? '—' : (totals?.calls ?? 0).toLocaleString() },
          { label: 'Tokens', value: isLoading ? '—' : (totals?.tokens ?? 0).toLocaleString() },
          { label: 'Estimated Cost', value: isLoading ? '—' : fmtCost(totals?.estimated_cost_usd ?? 0) },
          { label: 'Error Rate', value: isLoading ? '—' : `${((totals?.error_rate ?? 0) * 100).toFixed(1)}%` },
        ].map((k) => (
          <div key={k.label} className="bg-white border border-gray-100 rounded-xl p-4 shadow-sm">
            <p className="text-[11px] font-bold uppercase tracking-wide text-gray-400">{k.label}</p>
            <p className="text-2xl font-bold text-gray-900 mt-1">{k.value}</p>
          </div>
        ))}
      </div>

      {/* By service */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
        <h2 className="text-sm font-semibold text-gray-700 mb-3">By Service</h2>
        {services.length === 0 ? (
          <p className="text-sm text-gray-400 py-6 text-center">No usage recorded yet for this range.</p>
        ) : (
          <div className="space-y-2">
            {services.map((s) => (
              <div key={s.service} className="flex items-center gap-3 text-sm">
                <span className="w-32 shrink-0 font-medium text-gray-700 truncate">{s.service}</span>
                <div className="flex-1 bg-gray-100 rounded-full h-3 overflow-hidden">
                  <div
                    className="h-full bg-brand-500 rounded-full"
                    style={{ width: `${(s.calls / maxCalls) * 100}%` }}
                  />
                </div>
                <span className="w-16 text-right text-gray-500">{s.calls.toLocaleString()}</span>
                <span className="w-24 text-right text-gray-400">{fmtCost(s.estimated_cost_usd)}</span>
                <span className={`w-16 text-right ${s.error_rate > 0.05 ? 'text-red-500' : 'text-gray-400'}`}>
                  {(s.error_rate * 100).toFixed(1)}%
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* By feature / user */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <h2 className="text-sm font-semibold text-gray-700 p-4 pb-0">Top Features &amp; Users</h2>
        <table className="w-full text-sm mt-2">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50">
              <th className="text-left text-xs font-semibold text-gray-500 uppercase px-4 py-2">Service</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase px-4 py-2">Feature</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase px-4 py-2">User / Process</th>
              <th className="text-right text-xs font-semibold text-gray-500 uppercase px-4 py-2">Calls</th>
              <th className="text-right text-xs font-semibold text-gray-500 uppercase px-4 py-2">Tokens</th>
              <th className="text-right text-xs font-semibold text-gray-500 uppercase px-4 py-2">Cost</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {(byFeature?.items ?? []).map((it, i) => (
              <tr key={i} className="hover:bg-gray-50">
                <td className="px-4 py-2 text-gray-700">{it.service}</td>
                <td className="px-4 py-2 text-gray-500">{it.feature ?? '—'}</td>
                <td className="px-4 py-2 text-gray-500">{it.user_email ?? it.user_id ?? 'system'}</td>
                <td className="px-4 py-2 text-right text-gray-700">{it.calls.toLocaleString()}</td>
                <td className="px-4 py-2 text-right text-gray-500">
                  {(it.input_tokens + it.output_tokens).toLocaleString()}
                </td>
                <td className="px-4 py-2 text-right text-gray-500">{fmtCost(it.estimated_cost_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {(byFeature?.items ?? []).length === 0 && (
          <p className="text-sm text-gray-400 py-6 text-center">No feature-level data yet.</p>
        )}
      </div>

      {/* Alert config */}
      {cfg && (
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4 space-y-3">
          <h2 className="text-sm font-semibold text-gray-700">Spike Alert Configuration</h2>
          <label className="flex items-center gap-2 text-sm text-gray-600">
            <input
              type="checkbox"
              checked={cfg.is_enabled}
              onChange={(e) => setConfigDraft({ ...cfg, is_enabled: e.target.checked })}
            />
            Send real notifications on usage spikes
          </label>
          <label className="block text-sm text-gray-600">
            Spike multiplier
            <input
              type="number" min={1.5} max={20} step={0.5}
              value={cfg.spike_multiplier}
              onChange={(e) => setConfigDraft({ ...cfg, spike_multiplier: Number(e.target.value) })}
              className="ml-2 w-20 border border-gray-200 rounded px-2 py-1"
            />
          </label>
          <label className="block text-sm text-gray-600">
            Notification emails (comma-separated)
            <input
              type="text"
              value={cfg.emails}
              onChange={(e) => setConfigDraft({ ...cfg, emails: e.target.value })}
              className="mt-1 w-full border border-gray-200 rounded px-2 py-1"
            />
          </label>
          <button
            onClick={() => saveConfig.mutate()}
            disabled={saveConfig.isPending}
            className="text-xs font-semibold px-3 py-1.5 rounded-lg bg-brand-500 text-white hover:bg-brand-600 disabled:opacity-50"
          >
            Save
          </button>
        </div>
      )}

      <button
        onClick={() => generateReport.mutate()}
        disabled={generateReport.isPending}
        className="flex items-center gap-2 text-sm font-semibold text-brand-600 hover:text-brand-700 disabled:opacity-50"
      >
        <Download size={15} />
        Generate API &amp; Token Usage Report
      </button>
      {generateReport.isSuccess && (
        <p className="text-xs text-green-600">Report queued — find it in Reports shortly.</p>
      )}
    </div>
  );
}
