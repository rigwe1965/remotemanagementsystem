import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi } from 'vitest';
import UsageMonitoringPage from './UsageMonitoringPage';
import api from '../api/client';

vi.mock('../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
}));

let currentUser = { id: 'u1', email: 'sa@test.local', role: 'superadmin' };
vi.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({ user: currentUser, token: 'tok', login: vi.fn(), mfaLogin: vi.fn(), logout: vi.fn() }),
}));

function renderWithQueryClient(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe('UsageMonitoringPage', () => {
  it('blocks roles below admin with a restricted-access message', () => {
    currentUser = { id: 'u3', email: 'tech@test.local', role: 'technician' };

    renderWithQueryClient(<UsageMonitoringPage />);

    expect(screen.getByText(/administrator access required/i)).toBeInTheDocument();
  });

  it('renders per-service usage stats for an admin', async () => {
    currentUser = { id: 'u2', email: 'admin@test.local', role: 'admin' };
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/admin/usage/summary') {
        return Promise.resolve({
          data: {
            totals: { calls: 120, tokens: 4000, estimated_cost_usd: 1.2345, error_rate: 0.01 },
            services: [{ service: 'anthropic', calls: 120, estimated_cost_usd: 1.2345, error_rate: 0.01 }],
            anomalies: [],
          },
        });
      }
      if (url === '/admin/usage/by-feature') {
        return Promise.resolve({ data: { items: [] } });
      }
      if (url === '/admin/usage/alert-config') {
        return Promise.resolve({
          data: { is_enabled: true, spike_multiplier: 3, notification_channels: {} },
        });
      }
      return Promise.resolve({ data: {} });
    });

    renderWithQueryClient(<UsageMonitoringPage />);

    expect(await screen.findByText('anthropic')).toBeInTheDocument();
  });

  it('renders per-service usage stats for a superadmin', async () => {
    currentUser = { id: 'u1', email: 'sa@test.local', role: 'superadmin' };
    vi.mocked(api.get).mockImplementation((url: string) => {
      if (url === '/admin/usage/summary') {
        return Promise.resolve({
          data: {
            totals: { calls: 120, tokens: 4000, estimated_cost_usd: 1.2345, error_rate: 0.01 },
            services: [{ service: 'anthropic', calls: 120, estimated_cost_usd: 1.2345, error_rate: 0.01 }],
            anomalies: [],
          },
        });
      }
      if (url === '/admin/usage/by-feature') {
        return Promise.resolve({ data: { items: [] } });
      }
      if (url === '/admin/usage/alert-config') {
        return Promise.resolve({
          data: { is_enabled: true, spike_multiplier: 3, notification_channels: {} },
        });
      }
      return Promise.resolve({ data: {} });
    });

    renderWithQueryClient(<UsageMonitoringPage />);

    expect(await screen.findByText('anthropic')).toBeInTheDocument();
  });
});
