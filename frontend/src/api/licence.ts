import api from './client';

/** GET /api/admin/licence/status. When no licence is being enforced only the first three fields are present. */
export interface LicenceStatus {
  enforced: boolean;
  /** not_enforced | unlicensed | active | expiring | grace | lapsed */
  state: string;
  /** Plain words for the admin, or null when there is nothing to say. */
  banner: string | null;
  customer?: string;
  tier?: string;
  endsOn?: string;
}

export function getLicenceStatus(): Promise<LicenceStatus> {
  return api.get<LicenceStatus>('/admin/licence/status').then((r) => r.data);
}
