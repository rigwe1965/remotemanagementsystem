import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { DollarSign, RefreshCw, Send, Trash2 } from 'lucide-react';
import api from '../api/client';

interface Invoice {
  id: string;
  invoice_number: string;
  customer_id: string;
  customer_name?: string;
  status: 'draft' | 'sent' | 'paid' | 'overdue' | 'cancelled';
  subtotal: number;
  tax: number;
  total: number;
  period_start: string;
  period_end: string;
  due_date?: string;
  created_at: string;
}

const STATUS_BADGE: Record<string, string> = {
  draft:     'bg-gray-100 text-gray-500',
  sent:      'bg-blue-100 text-blue-700',
  paid:      'bg-green-100 text-green-700',
  overdue:   'bg-red-100 text-red-600',
  cancelled: 'bg-gray-100 text-gray-400',
};

const fmt = (n: number) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(n);

export default function BillingPage() {
  const [statusFilter, setStatusFilter] = useState('');
  const [page, setPage] = useState(1);
  const qc = useQueryClient();

  const { data, isLoading, isFetching, refetch } = useQuery<{ items: Invoice[]; total: number; pages: number }>({
    queryKey: ['invoices', statusFilter, page],
    queryFn: () =>
      api.get('/billing/invoices', { params: { status: statusFilter || undefined, page, per_page: 20 } })
        .then((r) => r.data),
    placeholderData: (prev) => prev,
  });

  const sendInvoice = useMutation({
    mutationFn: (id: string) => api.post(`/billing/invoices/${id}/send`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['invoices'] }),
  });

  const deleteInvoice = useMutation({
    mutationFn: (id: string) => api.delete(`/billing/invoices/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['invoices'] }),
  });

  const invoices = data?.items ?? [];
  const totalPages = data?.pages ?? 1;

  const totals = invoices.reduce(
    (acc, inv) => ({ total: acc.total + inv.total, paid: acc.paid + (inv.status === 'paid' ? inv.total : 0) }),
    { total: 0, paid: 0 }
  );

  return (
    <div className="p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Billing</h1>
          <p className="text-sm text-gray-500">{data?.total ?? '—'} invoices</p>
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

      {/* Summary strip */}
      {invoices.length > 0 && (
        <div className="grid grid-cols-2 gap-4">
          <div className="bg-white border border-gray-100 rounded-xl p-4 shadow-xs">
            <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">Page Total</p>
            <p className="text-2xl font-bold text-gray-800 mt-1">{fmt(totals.total)}</p>
          </div>
          <div className="bg-white border border-gray-100 rounded-xl p-4 shadow-xs">
            <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">Paid (this page)</p>
            <p className="text-2xl font-bold text-green-600 mt-1">{fmt(totals.paid)}</p>
          </div>
        </div>
      )}

      {/* Filter */}
      <div className="flex gap-1 bg-gray-100 p-1 rounded-lg w-fit">
        {(['', 'draft', 'sent', 'paid', 'overdue'] as const).map((s) => (
          <button
            key={s || 'all'}
            onClick={() => { setStatusFilter(s); setPage(1); }}
            className={`px-3 py-1.5 text-xs font-semibold rounded-md transition capitalize ${
              statusFilter === s ? 'bg-white text-gray-800 shadow-xs' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {s || 'All'}
          </button>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-gray-100 shadow-xs overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50">
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Invoice #</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Customer</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Period</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Total</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Status</th>
              <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Due</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {isLoading
              ? Array.from({ length: 6 }).map((_, i) => (
                  <tr key={i}>
                    {Array.from({ length: 7 }).map((_, j) => (
                      <td key={j} className="px-4 py-3">
                        <div className="h-4 bg-gray-100 rounded-sm animate-pulse" />
                      </td>
                    ))}
                  </tr>
                ))
              : invoices.map((inv) => (
                  <tr key={inv.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3 font-mono text-xs text-gray-700 font-medium">{inv.invoice_number}</td>
                    <td className="px-4 py-3 text-gray-700">{inv.customer_name ?? inv.customer_id.slice(0, 8)}</td>
                    <td className="px-4 py-3 text-xs text-gray-400">
                      {new Date(inv.period_start).toLocaleDateString()} – {new Date(inv.period_end).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3 font-semibold text-gray-800">{fmt(inv.total)}</td>
                    <td className="px-4 py-3">
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${STATUS_BADGE[inv.status]}`}>
                        {inv.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-400">
                      {inv.due_date ? new Date(inv.due_date).toLocaleDateString() : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        {inv.status === 'draft' && (
                          <button
                            onClick={() => sendInvoice.mutate(inv.id)}
                            disabled={sendInvoice.isPending}
                            title="Send invoice"
                            className="p-1.5 rounded-sm hover:bg-brand-50 text-gray-400 hover:text-brand-600 transition"
                          >
                            <Send size={13} />
                          </button>
                        )}
                        {(inv.status === 'draft' || inv.status === 'cancelled') && (
                          <button
                            onClick={() => {
                              if (confirm('Delete this invoice?')) deleteInvoice.mutate(inv.id);
                            }}
                            title="Delete"
                            className="p-1.5 rounded-sm hover:bg-red-50 text-gray-400 hover:text-red-500 transition"
                          >
                            <Trash2 size={13} />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
          </tbody>
        </table>
        {!isLoading && invoices.length === 0 && (
          <div className="py-16 text-center text-gray-400">
            <DollarSign size={32} className="mx-auto mb-3 text-gray-200" />
            <p className="text-sm">No invoices found.</p>
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
