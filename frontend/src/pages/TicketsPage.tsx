import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Ticket, Search, RefreshCw } from 'lucide-react';
import api from '../api/client';
import type { Ticket as TicketType, PaginatedResponse } from '../api/types';

const STATUS_BADGE: Record<string, string> = {
  open:        'bg-sky-100 text-sky-700',
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

function fetchTickets(page: number, status: string, search: string): Promise<PaginatedResponse<TicketType>> {
  return api.get('/tickets/', { params: { page, per_page: 20, status: status || undefined, search: search || undefined } })
    .then((r) => r.data);
}

export default function TicketsPage() {
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState('open');
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');

  const handleSearch = (val: string) => {
    setSearch(val);
    clearTimeout((window as any)._ticketSearchTimer);
    (window as any)._ticketSearchTimer = setTimeout(() => {
      setDebouncedSearch(val);
      setPage(1);
    }, 300);
  };

  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['tickets', page, statusFilter, debouncedSearch],
    queryFn: () => fetchTickets(page, statusFilter, debouncedSearch),
    placeholderData: (prev) => prev,
  });

  const tickets = data?.items ?? [];
  const totalPages = data?.pages ?? 1;

  const isOverdue = (t: TicketType) =>
    t.sla_breach_at && new Date(t.sla_breach_at) < new Date() && t.status !== 'resolved' && t.status !== 'closed';

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Tickets</h1>
          <p className="text-sm text-gray-500">{data?.total ?? '—'} tickets</p>
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

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <div className="flex gap-1 bg-gray-100 p-1 rounded-lg">
          {['open', 'in_progress', 'waiting', 'resolved', ''].map((s) => (
            <button
              key={s || 'all'}
              onClick={() => { setStatusFilter(s); setPage(1); }}
              className={`px-3 py-1.5 text-xs font-semibold rounded-md transition ${
                statusFilter === s ? 'bg-white text-gray-800 shadow-xs' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {s.replace('_', ' ') || 'All'}
            </button>
          ))}
        </div>
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Search tickets…"
            value={search}
            onChange={(e) => handleSearch(e.target.value)}
            className="pl-8 pr-3 py-1.5 text-sm border border-gray-200 rounded-lg bg-white focus:outline-hidden focus:ring-2 focus:ring-brand-400 transition"
          />
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-100 shadow-xs overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50">
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Title</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Priority</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Status</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">SLA</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Created</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {isLoading
              ? Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i}>
                    {Array.from({ length: 5 }).map((_, j) => (
                      <td key={j} className="px-4 py-3">
                        <div className="h-4 bg-gray-100 rounded-sm animate-pulse" />
                      </td>
                    ))}
                  </tr>
                ))
              : tickets.map((t) => (
                  <tr key={t.id} className={`hover:bg-gray-50 transition-colors ${isOverdue(t) ? 'bg-red-50/40' : ''}`}>
                    <td className="px-4 py-3 font-medium text-gray-800 max-w-xs truncate">
                      {t.title}
                      {isOverdue(t) && (
                        <span className="ml-2 text-[10px] font-bold bg-red-100 text-red-600 px-1.5 py-0.5 rounded-full">SLA BREACH</span>
                      )}
                    </td>
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
                      {t.sla_breach_at ? new Date(t.sla_breach_at).toLocaleString() : '—'}
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
            <Ticket size={32} className="mx-auto mb-3 text-gray-200" />
            <p className="text-sm">No tickets found.</p>
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
