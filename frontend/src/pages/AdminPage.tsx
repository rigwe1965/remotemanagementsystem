import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Users, UserPlus, Trash2, RefreshCw, Copy, Eye, EyeOff, Shield, Lock } from 'lucide-react';
import api from '../api/client';
import type { User } from '../api/types';
import { apiErrorMessage } from '../api/errors';

interface UserListResponse {
  items: User[];
  total: number;
  pages: number;
}

const ROLE_OPTIONS = ['admin', 'technician', 'viewer', 'client'] as const;
const ROLE_BADGE: Record<string, string> = {
  superadmin: 'bg-purple-100 text-purple-700',
  admin:      'bg-red-100 text-red-600',
  technician: 'bg-amber-100 text-amber-700',
  viewer:     'bg-green-100 text-green-700',
  client:     'bg-sky-100 text-sky-700',
};

const emptyForm = { email: '', full_name: '', password: '', role: 'technician' as const, must_change_password: true };

export default function AdminPage() {
  const [tab, setTab] = useState<'users' | 'org'>('users');
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ ...emptyForm });
  const [showToken, setShowToken] = useState(false);
  const [copied, setCopied] = useState(false);
  const [page, setPage] = useState(1);
  const qc = useQueryClient();

  const { data, isLoading, refetch } = useQuery<UserListResponse>({
    queryKey: ['admin-users', page],
    queryFn: () => api.get('/admin/users', { params: { page, per_page: 20 } }).then((r) => r.data),
    placeholderData: (prev) => prev,
  });

  const { data: orgTokenData } = useQuery<{ token: string }>({
    queryKey: ['org-token'],
    queryFn: () => api.get('/admin/org-token').then((r) => r.data),
    enabled: tab === 'org',
  });

  const createUser = useMutation({
    mutationFn: (body: typeof form) => api.post('/admin/users', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-users'] });
      setShowForm(false);
      setForm({ ...emptyForm });
    },
  });

  const deleteUser = useMutation({
    mutationFn: (id: string) => api.delete(`/admin/users/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-users'] }),
  });

  const unlockUser = useMutation({
    mutationFn: (id: string) => api.post(`/admin/users/${id}/unlock`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-users'] }),
  });

  const users = data?.items ?? [];
  const totalPages = data?.pages ?? 1;

  const copyToken = () => {
    if (orgTokenData?.token) {
      navigator.clipboard.writeText(orgTokenData.token);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className="p-6 space-y-5">
      <div>
        <h1 className="text-xl font-bold text-gray-900">Admin</h1>
        <p className="text-sm text-gray-500">User management and organisation settings</p>
      </div>

      <div className="flex gap-1 bg-gray-100 p-1 rounded-lg w-fit">
        {(['users', 'org'] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-1.5 text-xs font-semibold rounded-md transition capitalize ${
              tab === t ? 'bg-white text-gray-800 shadow-xs' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {t === 'users' ? 'Users' : 'Organisation'}
          </button>
        ))}
      </div>

      {tab === 'users' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-gray-500">{data?.total ?? '—'} users</p>
            <div className="flex gap-2">
              <button onClick={() => refetch()}
                className="flex items-center gap-2 text-sm text-gray-500 hover:text-brand-600 transition">
                <RefreshCw size={14} />
                Refresh
              </button>
              <button
                onClick={() => setShowForm((v) => !v)}
                className="flex items-center gap-2 px-3 py-1.5 bg-brand-500 text-white text-xs font-semibold rounded-lg hover:bg-brand-600 transition"
              >
                <UserPlus size={13} />
                Add User
              </button>
            </div>
          </div>

          {/* Create user form */}
          {showForm && (
            <div className="bg-white border border-brand-100 rounded-xl p-5 shadow-xs space-y-3">
              <h3 className="text-sm font-bold text-gray-800">New User</h3>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-medium text-gray-600 block mb-1">Full name</label>
                  <input
                    type="text"
                    value={form.full_name}
                    onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))}
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-brand-400"
                    placeholder="Jane Smith"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-gray-600 block mb-1">Email</label>
                  <input
                    type="email"
                    value={form.email}
                    onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-brand-400"
                    placeholder="jane@example.com"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-gray-600 block mb-1">Password</label>
                  <input
                    type="password"
                    value={form.password}
                    onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-brand-400"
                    placeholder="Min. 8 characters"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-gray-600 block mb-1">Role</label>
                  <select
                    value={form.role}
                    onChange={(e) => setForm((f) => ({ ...f, role: e.target.value as any }))}
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-brand-400"
                  >
                    {ROLE_OPTIONS.map((r) => (
                      <option key={r} value={r}>{r}</option>
                    ))}
                  </select>
                </div>
              </div>
              <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.must_change_password}
                  onChange={(e) => setForm((f) => ({ ...f, must_change_password: e.target.checked }))}
                  className="rounded-sm border-gray-300 text-brand-500 focus:ring-brand-400"
                />
                Force password change on first login
              </label>
              <div className="flex gap-2 pt-1">
                <button
                  onClick={() => createUser.mutate(form)}
                  disabled={!form.email || !form.password || createUser.isPending}
                  className="px-4 py-2 bg-brand-500 text-white text-sm font-semibold rounded-lg hover:bg-brand-600 disabled:opacity-50 transition"
                >
                  {createUser.isPending ? 'Creating…' : 'Create User'}
                </button>
                <button
                  onClick={() => { setShowForm(false); setForm({ ...emptyForm }); }}
                  className="px-4 py-2 border border-gray-200 text-gray-600 text-sm font-semibold rounded-lg hover:bg-gray-50 transition"
                >
                  Cancel
                </button>
              </div>
              {createUser.isError && (
                <p className="text-xs text-red-600">{apiErrorMessage(createUser.error, 'Failed to create user')}</p>
              )}
            </div>
          )}

          <div className="bg-white rounded-xl border border-gray-100 shadow-xs overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50">
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Name</th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Email</th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">Role</th>
                  <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wide px-4 py-3">MFA</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {isLoading
                  ? Array.from({ length: 6 }).map((_, i) => (
                      <tr key={i}>
                        {Array.from({ length: 5 }).map((_, j) => (
                          <td key={j} className="px-4 py-3">
                            <div className="h-4 bg-gray-100 rounded-sm animate-pulse" />
                          </td>
                        ))}
                      </tr>
                    ))
                  : users.map((u) => (
                      <tr key={u.id} className="hover:bg-gray-50 transition-colors">
                        <td className="px-4 py-3 font-medium text-gray-800">{u.full_name || '—'}</td>
                        <td className="px-4 py-3 text-gray-500 text-xs">{u.email}</td>
                        <td className="px-4 py-3">
                          <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${ROLE_BADGE[u.role] ?? ''}`}>
                            {u.role}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span title={u.mfa_enabled ? 'MFA enabled' : 'MFA disabled'}>
                            <Shield size={14} className={u.mfa_enabled ? 'text-green-500' : 'text-gray-200'} />
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          {u.role !== 'superadmin' && (
                            <div className="flex items-center gap-1.5">
                              <button
                                onClick={() => unlockUser.mutate(u.id)}
                                title="Unlock account"
                                className="p-1.5 rounded-sm hover:bg-amber-50 text-gray-300 hover:text-amber-500 transition"
                              >
                                <Lock size={13} />
                              </button>
                              <button
                                onClick={() => {
                                  if (confirm(`Delete user ${u.email}? This cannot be undone.`)) {
                                    deleteUser.mutate(u.id);
                                  }
                                }}
                                title="Delete user"
                                className="p-1.5 rounded-sm hover:bg-red-50 text-gray-300 hover:text-red-500 transition"
                              >
                                <Trash2 size={13} />
                              </button>
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
              </tbody>
            </table>
            {!isLoading && users.length === 0 && (
              <div className="py-12 text-center text-gray-400">
                <Users size={32} className="mx-auto mb-3 text-gray-200" />
                <p className="text-sm">No users found.</p>
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
      )}

      {tab === 'org' && (
        <div className="space-y-4 max-w-lg">
          <div className="bg-white border border-gray-100 rounded-xl p-5 shadow-xs space-y-3">
            <h3 className="text-sm font-bold text-gray-800">Agent Registration Token</h3>
            <p className="text-xs text-gray-500">
              Agents use this token to self-register with the RMM. Keep it confidential.
            </p>
            <div className="flex items-center gap-2">
              <code className={`flex-1 text-xs font-mono bg-gray-900 text-green-400 px-3 py-2 rounded-lg truncate ${!showToken ? 'tracking-widest text-gray-700 bg-gray-100' : ''}`}>
                {showToken ? (orgTokenData?.token ?? 'Loading…') : '••••••••••••••••••••••••••••••'}
              </code>
              <button
                onClick={() => setShowToken((v) => !v)}
                className="p-2 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition shrink-0"
              >
                {showToken ? <EyeOff size={15} /> : <Eye size={15} />}
              </button>
              <button
                onClick={copyToken}
                disabled={!orgTokenData?.token}
                className="p-2 rounded-lg hover:bg-brand-50 text-gray-400 hover:text-brand-600 transition shrink-0"
                title="Copy token"
              >
                <Copy size={15} />
              </button>
            </div>
            {copied && <p className="text-xs text-green-600">Copied to clipboard!</p>}
          </div>

          <div className="bg-amber-50 border border-amber-100 rounded-xl p-4">
            <p className="text-xs font-semibold text-amber-700 mb-1">Agent deployment command</p>
            <code className="text-xs font-mono text-gray-700 block whitespace-pre-wrap">
              {`python setup_agent.py <server_ip> ${showToken && orgTokenData?.token ? orgTokenData.token : '<ORG_TOKEN>'}`}
            </code>
          </div>
        </div>
      )}
    </div>
  );
}
