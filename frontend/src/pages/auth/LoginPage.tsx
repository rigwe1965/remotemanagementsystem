import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Monitor, Eye, EyeOff, Shield } from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';

export default function LoginPage() {
  const { login, mfaLogin } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  // MFA step
  const [mfaToken, setMfaToken] = useState('');
  const [mfaCode, setMfaCode] = useState('');
  const [mfaStep, setMfaStep] = useState(false);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) { setError('Email and password required.'); return; }
    setError('');
    setLoading(true);
    const result = await login(email, password);
    setLoading(false);
    if (result.mfaRequired) {
      setMfaToken(result.mfaToken!);
      setMfaStep(true);
    } else if (result.error) {
      setError(
        result.error === 'account_locked'
          ? 'Account locked after too many failed attempts. Wait 5 minutes or contact admin.'
          : 'Invalid email or password.'
      );
    } else {
      navigate('/dashboard', { replace: true });
    }
  };

  const handleMfa = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!mfaCode || mfaCode.length !== 6) { setError('Enter a 6-digit code.'); return; }
    setError('');
    setLoading(true);
    const result = await mfaLogin(mfaToken, mfaCode);
    setLoading(false);
    if (result.error) {
      setError('Invalid or expired code. Try again.');
    } else {
      navigate('/dashboard', { replace: true });
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-linear-to-br from-brand-700 to-brand-500 rounded-2xl mb-4 shadow-lg">
            <Monitor className="text-brand-300" size={28} />
          </div>
          <h1 className="text-2xl font-bold text-gray-900">RMM System</h1>
          <p className="text-sm text-gray-500 mt-1">Remote Monitoring &amp; Management</p>
        </div>

        {/* Card */}
        <div className="bg-white rounded-2xl shadow-md border border-gray-100 p-8">
          {!mfaStep ? (
            <>
              <h2 className="text-lg font-semibold text-gray-800 mb-6">Sign in</h2>
              <form onSubmit={handleLogin} className="space-y-4">
                <div>
                  <label htmlFor="login-email" className="block text-xs font-semibold text-brand-600 mb-1.5">Email address</label>
                  <input
                    id="login-email"
                    type="email"
                    autoComplete="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="admin@company.com"
                    className="w-full px-3 py-2.5 text-sm border border-gray-200 rounded-lg bg-gray-50 focus:outline-hidden focus:ring-2 focus:ring-brand-400 focus:border-transparent transition"
                  />
                </div>
                <div>
                  <label htmlFor="login-password" className="block text-xs font-semibold text-brand-600 mb-1.5">Password</label>
                  <div className="relative">
                    <input
                      id="login-password"
                      type={showPw ? 'text' : 'password'}
                      autoComplete="current-password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="••••••••"
                      className="w-full px-3 py-2.5 pr-10 text-sm border border-gray-200 rounded-lg bg-gray-50 focus:outline-hidden focus:ring-2 focus:ring-brand-400 focus:border-transparent transition"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPw((s) => !s)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                    >
                      {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </div>
                {error && (
                  <div className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
                    {error}
                  </div>
                )}
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full py-2.5 bg-brand-500 hover:bg-brand-600 text-white text-sm font-semibold rounded-lg transition shadow-xs disabled:opacity-60 mt-2"
                >
                  {loading ? 'Signing in…' : 'Sign In →'}
                </button>
              </form>
            </>
          ) : (
            <>
              <div className="flex items-center gap-3 mb-6">
                <Shield className="text-brand-500" size={22} />
                <h2 className="text-lg font-semibold text-gray-800">Two-Factor Auth</h2>
              </div>
              <p className="text-sm text-gray-500 mb-5">Enter the 6-digit code from your authenticator app.</p>
              <form onSubmit={handleMfa} className="space-y-4">
                <input
                  type="text"
                  inputMode="numeric"
                  maxLength={6}
                  value={mfaCode}
                  onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, ''))}
                  placeholder="123456"
                  className="w-full px-3 py-2.5 text-sm text-center tracking-widest border border-gray-200 rounded-lg bg-gray-50 focus:outline-hidden focus:ring-2 focus:ring-brand-400 transition"
                />
                {error && (
                  <div className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
                    {error}
                  </div>
                )}
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full py-2.5 bg-brand-500 hover:bg-brand-600 text-white text-sm font-semibold rounded-lg transition shadow-xs disabled:opacity-60"
                >
                  {loading ? 'Verifying…' : 'Verify →'}
                </button>
                <button
                  type="button"
                  onClick={() => { setMfaStep(false); setError(''); setMfaCode(''); }}
                  className="w-full text-sm text-gray-400 hover:text-gray-600"
                >
                  ← Back to login
                </button>
              </form>
            </>
          )}
        </div>

        <p className="text-center text-xs text-gray-400 mt-6">Authorized access only</p>
      </div>
    </div>
  );
}
