import { useQuery } from '@tanstack/react-query';
import { ShieldAlert } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { getLicenceStatus } from '../api/licence';

/**
 * Tells an admin about the licence, but only when one is being enforced and there is something to say (it is ending, it has
 * ended, a limit is passed, or none was found). Nothing is shown to anyone else, and nothing at all on a deployment that does
 * not enforce a licence, which is every deployment until one is sold. Never blocks anything: it is only words.
 */
export default function LicenceBanner() {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin' || user?.role === 'superadmin';
  const { data } = useQuery({ queryKey: ['licence'], queryFn: getLicenceStatus, enabled: isAdmin, staleTime: 5 * 60_000, retry: false });

  if (!isAdmin || !data?.enforced || !data.banner) return null;
  const urgent = data.state === 'unlicensed' || data.state === 'lapsed';
  return (
    <div
      role="status"
      className={`flex items-start gap-3 px-6 py-3 text-sm border-b ${urgent ? 'bg-red-50 text-red-800 border-red-200' : 'bg-amber-50 text-amber-800 border-amber-200'}`}
    >
      <ShieldAlert size={18} className="mt-0.5 shrink-0" aria-hidden="true" />
      <p>{data.banner}</p>
    </div>
  );
}
