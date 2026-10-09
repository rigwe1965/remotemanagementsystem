import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Lock, Shield, CheckCircle } from 'lucide-react';
import api from '../api/client';
import { useAuth } from '../contexts/AuthContext';
import { apiErrorMessage } from '../api/errors';

interface MFASetupData {
  secret: string;
  qr_code: string;
  backup_codes: string[];
}

export default function ProfilePage() {
  const { user } = useAuth();
  const [tab, setTab] = useState<'profile' | 'password' | 'mfa'>('profile');

  const [pwForm, setPwForm] = useState({ current_password: '', new_password: '', confirm: '' });
  const [pwMsg, setPwMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);

  const [mfaSetup, setMfaSetup] = useState<MFASetupData | null>(null);
  const [mfaCode, setMfaCode] = useState('');
  const [mfaMsg, setMfaMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);

  const changePassword = useMutation({
    mutationFn: (body: { current_password: string; new_password: string }) =>
      api.put('/auth/me/password', body),
    onSuccess: () => {
      setPwMsg({ type: 'ok', text: 'Password changed.' });
      setPwForm({ current_password: '', new_password: '', confirm: '' });
    },
    onError: (e: unknown) => {
      setPwMsg({ type: 'err', text: apiErrorMessage(e, 'Failed to change password') });
    },
  });

  const setupMFA = useMutation({
    mutationFn: () => api.post('/auth/mfa/setup').then((r) => r.data as MFASetupData),
    onSuccess: (data) => setMfaSetup(data),
  });

  const enableMFA = useMutation({
    mutationFn: (code: string) => api.post('/auth/mfa/enable', { totp_code: code }),
    onSuccess: () => {
      setMfaMsg({ type: 'ok', text: 'MFA enabled successfully.' });
      setMfaSetup(null);
      setMfaCode('');
    },
    onError: (e: unknown) => {
      setMfaMsg({ type: 'err', text: apiErrorMessage(e, 'Invalid code') });
    },
  });

  const handlePwSubmit = () => {
    if (pwForm.new_password !== pwForm.confirm) {
      setPwMsg({ type: 'err', text: 'Passwords do not match.' });
      return;
    }
    if (pwForm.new_password.length < 8) {
      setPwMsg({ type: 'err', text: 'Minimum 8 characters.' });
      return;
    }
    setPwMsg(null);
    changePassword.mutate({ current_password: pwForm.current_password, new_password: pwForm.new_password });
  };

  const ROLE_BADGE: Record<string, string> = {
    superadmin: 'bg-purple-100 text-purple-700',
    admin:      'bg-red-100 text-red-600',
    technician: 'bg-amber-100 text-amber-700',
    viewer:     'bg-green-100 text-green-700',
    client:     'bg-sky-100 text-sky-700',
  };

  return (
    <div className="p-6 space-y-5">
      <div>
        <h1 className="text-xl font-bold text-gray-900">Profile</h1>
        <p className="text-sm text-gray-500">Account settings and security</p>
      </div>

      <div className="flex gap-1 bg-gray-100 p-1 rounded-lg w-fit">
        {(['profile', 'password', 'mfa'] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-1.5 text-xs font-semibold rounded-md transition capitalize ${
              tab === t ? 'bg-white text-gray-800 shadow-xs' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {t === 'mfa' ? 'Two-Factor Auth' : t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === 'profile' && (
        <div className="bg-white border border-gray-100 rounded-xl p-6 shadow-xs max-w-md space-y-4">
          <div className="flex items-center gap-4">
            <div className="w-14 h-14 rounded-full bg-linear-to-br from-brand-500 to-brand-300 flex items-center justify-center text-white text-xl font-bold">
              {(user?.full_name || user?.email || '?').split(' ').map((w) => w[0]).join('').slice(0, 2).toUpperCase()}
            </div>
            <div>
              <p className="font-bold text-gray-900">{user?.full_name || '—'}</p>
              <p className="text-sm text-gray-500">{user?.email}</p>
              <span className={`text-xs font-bold px-2 py-0.5 rounded-full mt-1 inline-block ${ROLE_BADGE[user?.role ?? 'viewer']}`}>
                {user?.role?.toUpperCase()}
              </span>
            </div>
          </div>
          <div className="pt-2 border-t border-gray-100 space-y-2 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-gray-500">MFA</span>
              <span className={`font-semibold ${user?.mfa_enabled ? 'text-green-600' : 'text-gray-400'}`}>
                {user?.mfa_enabled ? 'Enabled' : 'Disabled'}
              </span>
            </div>
          </div>
        </div>
      )}

      {tab === 'password' && (
        <div className="bg-white border border-gray-100 rounded-xl p-6 shadow-xs max-w-md space-y-4">
          <h2 className="text-sm font-bold text-gray-800 flex items-center gap-2">
            <Lock size={15} className="text-brand-500" />
            Change Password
          </h2>
          <div className="space-y-3">
            {(['current_password', 'new_password', 'confirm'] as const).map((field) => (
              <div key={field}>
                <label className="text-xs font-medium text-gray-600 block mb-1 capitalize">
                  {field.replace(/_/g, ' ')}
                </label>
                <input
                  type="password"
                  value={pwForm[field]}
                  onChange={(e) => setPwForm((f) => ({ ...f, [field]: e.target.value }))}
                  className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-brand-400"
                />
              </div>
            ))}
          </div>
          {pwMsg && (
            <p className={`text-xs font-medium ${pwMsg.type === 'ok' ? 'text-green-600' : 'text-red-600'}`}>
              {pwMsg.text}
            </p>
          )}
          <button
            onClick={handlePwSubmit}
            disabled={!pwForm.current_password || !pwForm.new_password || changePassword.isPending}
            className="w-full py-2 bg-brand-500 text-white text-sm font-semibold rounded-lg hover:bg-brand-600 disabled:opacity-50 transition"
          >
            {changePassword.isPending ? 'Saving…' : 'Update Password'}
          </button>
        </div>
      )}

      {tab === 'mfa' && (
        <div className="bg-white border border-gray-100 rounded-xl p-6 shadow-xs max-w-md space-y-4">
          <h2 className="text-sm font-bold text-gray-800 flex items-center gap-2">
            <Shield size={15} className="text-brand-500" />
            Two-Factor Authentication
          </h2>

          {user?.mfa_enabled ? (
            <div className="flex items-center gap-2 text-sm text-green-600">
              <CheckCircle size={16} />
              MFA is active on your account.
            </div>
          ) : !mfaSetup ? (
            <div className="space-y-3">
              <p className="text-sm text-gray-500">
                Add an extra layer of security using a TOTP authenticator app (Google Authenticator, Authy, etc.).
              </p>
              <button
                onClick={() => setupMFA.mutate()}
                disabled={setupMFA.isPending}
                className="flex items-center gap-2 px-4 py-2 bg-brand-500 text-white text-sm font-semibold rounded-lg hover:bg-brand-600 disabled:opacity-50 transition"
              >
                {setupMFA.isPending ? 'Generating…' : 'Set Up MFA'}
              </button>
            </div>
          ) : (
            <div className="space-y-4">
              <p className="text-sm text-gray-600">Scan this QR code with your authenticator app:</p>
              <div className="flex justify-center">
                <img
                  src={`data:image/png;base64,${mfaSetup.qr_code}`}
                  alt="MFA QR code"
                  className="w-48 h-48 border border-gray-200 rounded-lg"
                />
              </div>
              <div>
                <p className="text-xs text-gray-500 mb-1">Or enter secret manually:</p>
                <code className="text-xs font-mono bg-gray-100 px-3 py-1.5 rounded-lg block break-all">
                  {mfaSetup.secret}
                </code>
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600 block mb-1">Enter 6-digit code to verify</label>
                <input
                  type="text"
                  value={mfaCode}
                  onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  maxLength={6}
                  placeholder="000000"
                  className="w-32 px-3 py-2 text-sm font-mono text-center border border-gray-200 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-brand-400"
                />
              </div>
              {mfaMsg && (
                <p className={`text-xs font-medium ${mfaMsg.type === 'ok' ? 'text-green-600' : 'text-red-600'}`}>
                  {mfaMsg.text}
                </p>
              )}
              <button
                onClick={() => enableMFA.mutate(mfaCode)}
                disabled={mfaCode.length !== 6 || enableMFA.isPending}
                className="w-full py-2 bg-brand-500 text-white text-sm font-semibold rounded-lg hover:bg-brand-600 disabled:opacity-50 transition"
              >
                {enableMFA.isPending ? 'Verifying…' : 'Enable MFA'}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
