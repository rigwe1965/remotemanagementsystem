import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { MessageSquare, Plus, X, RefreshCw } from 'lucide-react';
import api from '../api/client';
import { useAuth } from '../contexts/AuthContext';
import { apiErrorMessage } from '../api/errors';
import type { Ticket, PaginatedResponse } from '../api/types';

const STATUS_BADGE: Record<string, string> = {
  open:        'bg-red-100 text-red-600',
  in_progress: 'bg-amber-100 text-amber-700',
  waiting:     'bg-purple-100 text-purple-700',
  resolved:    'bg-green-100 text-green-700',
  closed:      'bg-gray-100 text-gray-500',
};

const PRIORITY_BADGE: Record<string, string> = {
  critical: 'bg-red-100 text-red-600',
  high:     'bg-orange-100 text-orange-600',
  medium:   'bg-amber-100 text-amber-700',
  low:      'bg-gray-100 text-gray-500',
};

const emptyForm = { title: '', description: '', priority: 'medium' as const };

export default function ClientPortalPage() {
  const { user } = useAuth();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ ...emptyForm });
  const [submitMsg, setSubmitMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);
  const [page, setPage] = useState(1);
  const qc = useQueryClient();

  const { data, isLoading, isFetching, refetch } = useQuery<PaginatedResponse<Ticket>>({
    queryKey: ['client-tickets', page],
    queryFn: () =>
      api.get('/tickets/', { params: { page, per_page: 10 } }).then((r) => r.data),
    placeholderData: (prev) => prev,
  });

  const createTicket = useMutation({
    mutationFn: (body: typeof form) => api.post('/tickets/', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['client-tickets'] });
      setForm({ ...emptyForm });
      setShowForm(false);
      setSubmitMsg({ type: 'ok', text: 'Ticket submitted. Our team will review it shortly.' });
      setTimeout(() => setSubmitMsg(null), 5000);
    },
    onError: (e: unknown) => {
      setSubmitMsg({ type: 'err', text: apiErrorMessage(e, 'Failed to submit ticket') });
    },
  });

  const tickets = data?.items ?? [];
  const totalPages = data?.pages ?? 1;

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Portal header */}
      <div className="bg-white border-b border-gray-100 shadow-xs">
        <div className="max-w-4xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-brand-500 rounded-lg flex items-center justify-center">
              <MessageSquare size={16} className="text-white" />
            </div>
            <div>
              <span className="font-bold text-brand-600 text-lg">Support Portal</span>
              <p className="text-xs text-gray-400">Submit and track your support tickets</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm text-gray-500">
              {user?.full_name || user?.email}
            </span>
          </div>
        </div>
      </div>

      <div className="max-w-4xl mx-auto px-6 py-6 space-y-5">
        {/* Submit ticket toggle */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-lg font-bold text-gray-900">My Tickets</h1>
            <p className="text-sm text-gray-500">{data?.total ?? '—'} total</p>
          </div>
          <div className="flex gap-2">
            <button onClick={() => refetch()} disabled={isFetching}
              className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-brand-600 transition disabled:opacity-50">
              <RefreshCw size={14} className={isFetching ? 'animate-spin' : ''} />
            </button>
            <button
              onClick={() => { setShowForm((v) => !v); setSubmitMsg(null); }}
              className="flex items-center gap-2 px-4 py-2 bg-brand-500 text-white text-sm font-semibold rounded-lg hover:bg-brand-600 transition"
            >
              {showForm ? <X size={14} /> : <Plus size={14} />}
              {showForm ? 'Cancel' : 'New Ticket'}
            </button>
          </div>
        </div>

        {/* Feedback message */}
        {submitMsg && (
          <div className={`px-4 py-3 rounded-lg text-sm font-medium ${
            submitMsg.type === 'ok' ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-700 border border-red-200'
          }`}>
            {submitMsg.text}
          </div>
        )}

        {/* New ticket form */}
        {showForm && (
          <div className="bg-white border border-brand-100 rounded-xl p-5 shadow-xs space-y-4">
            <h2 className="text-sm font-bold text-gray-800">Submit New Ticket</h2>
            <div className="space-y-3">
              <div>
                <label className="text-xs font-medium text-gray-600 block mb-1">Subject *</label>
                <input
                  type="text"
                  value={form.title}
                  onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                  placeholder="Brief description of your issue"
                  className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-brand-400"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600 block mb-1">Priority</label>
                <select
                  value={form.priority}
                  onChange={(e) => setForm((f) => ({ ...f, priority: e.target.value as any }))}
                  className="w-40 px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-brand-400 bg-white"
                >
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                  <option value="critical">Critical</option>
                </select>
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600 block mb-1">Details</label>
                <textarea
                  value={form.description}
                  onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                  placeholder="Please describe your issue in full…"
                  rows={4}
                  className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-brand-400 resize-none"
                />
              </div>
            </div>
            <button
              onClick={() => {
                if (!form.title.trim()) { setSubmitMsg({ type: 'err', text: 'Subject is required.' }); return; }
                createTicket.mutate(form);
              }}
              disabled={createTicket.isPending}
              className="w-full py-2.5 bg-brand-500 text-white text-sm font-semibold rounded-lg hover:bg-brand-600 disabled:opacity-50 transition"
            >
              {createTicket.isPending ? 'Submitting…' : 'Submit Ticket'}
            </button>
          </div>
        )}

        {/* Ticket list */}
        <div className="bg-white rounded-xl border border-gray-100 shadow-xs overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Subject</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Priority</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Status</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Submitted</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {isLoading
                ? Array.from({ length: 5 }).map((_, i) => (
                    <tr key={i}>
                      {Array.from({ length: 4 }).map((_, j) => (
                        <td key={j} className="px-4 py-3">
                          <div className="h-4 bg-gray-100 rounded-sm animate-pulse" />
                        </td>
                      ))}
                    </tr>
                  ))
                : tickets.map((t) => (
                    <tr key={t.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3 font-medium text-gray-800 max-w-xs">{t.title}</td>
                      <td className="px-4 py-3">
                        <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${PRIORITY_BADGE[t.priority]}`}>
                          {t.priority}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${STATUS_BADGE[t.status]}`}>
                          {t.status.replace('_', ' ')}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-400">
                        {new Date(t.created_at).toLocaleDateString()}
                      </td>
                    </tr>
                  ))}
            </tbody>
          </table>
          {!isLoading && tickets.length === 0 && (
            <div className="py-16 text-center text-gray-400">
              <MessageSquare size={32} className="mx-auto mb-3 text-gray-200" />
              <p className="text-sm">No tickets yet. Submit one above.</p>
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
    </div>
  );
}
