import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ThirdPartyPortalProvider } from '../context/ThirdPartyPortalProvider';
import {
  setThirdPartyPortalSession,
  clearThirdPartyPortalSession,
} from '../api/thirdPartyPortalClient';
import ThirdPartyPortalClaimDetail from './ThirdPartyPortalClaimDetail';

const mockFetch = vi.fn();

function renderPage(claimId = 'CLM-2') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ThirdPartyPortalProvider>
        <MemoryRouter initialEntries={[`/third-party-portal/claims/${claimId}`]}>
          <Routes>
            <Route
              path="/third-party-portal/claims/:claimId"
              element={<ThirdPartyPortalClaimDetail />}
            />
            <Route
              path="/third-party-portal/login"
              element={<div data-testid="login">Login</div>}
            />
          </Routes>
        </MemoryRouter>
      </ThirdPartyPortalProvider>
    </QueryClientProvider>
  );
}

describe('ThirdPartyPortalClaimDetail', () => {
  beforeEach(() => {
    mockFetch.mockReset();
    vi.stubGlobal('fetch', mockFetch);
    clearThirdPartyPortalSession();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('redirects to login when no session', () => {
    renderPage();
    expect(screen.getByTestId('login')).toBeInTheDocument();
  });

  it('shows error state on fetch failure', async () => {
    setThirdPartyPortalSession({ claimId: 'CLM-2', token: 'tok' });
    mockFetch.mockResolvedValue({
      ok: false,
      status: 404,
      text: async () => JSON.stringify({ detail: 'Not found' }),
    } as Response);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText('Not found')).toBeInTheDocument();
    });
  });

  it('renders claim detail on successful fetch', async () => {
    setThirdPartyPortalSession({ claimId: 'CLM-2', token: 'tok' });
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        id: 'CLM-2',
        status: 'open',
        claim_type: 'partial_loss',
        vehicle_year: 2023,
        vehicle_make: 'Toyota',
        vehicle_model: 'Camry',
        vin: 'VIN456',
        incident_date: '2025-02-01',
        incident_description: 'Side swipe',
        follow_up_messages: [],
      }),
    } as Response);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText(/XC-CLM-2/)).toBeInTheDocument();
      expect(screen.getAllByText(/2023 Toyota Camry/).length).toBeGreaterThanOrEqual(1);
    });
  });

  it('shows tabs for overview, liability, communications', async () => {
    setThirdPartyPortalSession({ claimId: 'CLM-2', token: 'tok' });
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        id: 'CLM-2',
        status: 'open',
        claim_type: 'partial_loss',
        vehicle_year: 2023,
        vehicle_make: 'Toyota',
        vehicle_model: 'Camry',
        vin: 'VIN456',
        follow_up_messages: [],
      }),
    } as Response);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText('Claim Overview')).toBeInTheDocument();
      expect(screen.getByText('Liability & Subrogation')).toBeInTheDocument();
      expect(screen.getByText('Communications (0)')).toBeInTheDocument();
    });
  });
});
