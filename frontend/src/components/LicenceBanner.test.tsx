import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import LicenceBanner from './LicenceBanner';
import api from '../api/client';

vi.mock('../api/client', () => ({ default: { get: vi.fn(), post: vi.fn() } }));
const auth = vi.hoisted(() => ({ role: 'admin' as string | undefined }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: auth.role ? { role: auth.role } : null }) }));

function show() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <LicenceBanner />
    </QueryClientProvider>,
  );
}

describe('LicenceBanner', () => {
  beforeEach(() => {
    vi.mocked(api.get).mockReset();
    auth.role = 'admin';
  });

  it('shows the words an admin needs when a licence is enforced and is ending', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { enforced: true, state: 'expiring', banner: 'Your licence ends on 2027-11-30. Renew it to keep adding more.' } });
    show();
    expect(await screen.findByRole('status')).toHaveTextContent('Your licence ends on 2027-11-30');
    expect(api.get).toHaveBeenCalledWith('/admin/licence/status');
  });

  it('shows a lapsed or missing licence as urgent, and says that existing things keep working', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { enforced: true, state: 'unlicensed', banner: 'No valid licence was found. Everything already set up keeps working.' } });
    show();
    const bar = await screen.findByRole('status');
    expect(bar).toHaveTextContent('keeps working');
    expect(bar.className).toContain('bg-red-50');
  });

  it('shows nothing on a deployment that does not enforce a licence', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { enforced: false, state: 'not_enforced', banner: null } });
    show();
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('shows nothing when a licence is fine and there is nothing to say', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { enforced: true, state: 'active', banner: null } });
    show();
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('is for admins only: other roles never ask and never see it', async () => {
    for (const role of ['technician', 'viewer', 'client', undefined]) {
      auth.role = role;
      vi.mocked(api.get).mockResolvedValue({ data: { enforced: true, state: 'lapsed', banner: 'Your licence ended.' } });
      const { unmount } = show();
      await new Promise((r) => setTimeout(r, 20));
      expect(screen.queryByRole('status')).toBeNull();
      unmount();
    }
    expect(api.get).not.toHaveBeenCalled();
  });

  it('quietly shows nothing if the status cannot be read', async () => {
    vi.mocked(api.get).mockRejectedValue(new Error('network'));
    show();
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(screen.queryByRole('status')).toBeNull();
  });
});
