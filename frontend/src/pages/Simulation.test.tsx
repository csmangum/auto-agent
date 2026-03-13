import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RoleSimulationProvider } from '../context/RoleSimulationContext';
import Simulation from './Simulation';

vi.mock('../api/queries', () => ({
  useClaims: vi.fn(() => ({ data: { claims: [], total: 0 }, isLoading: false, error: null })),
  useClaim: vi.fn(() => ({ data: null, isLoading: false, error: null })),
  useClaimHistory: vi.fn(() => ({ data: { history: [] }, isLoading: false, error: null })),
  queryKeys: { claim: (id: string) => ['claims', id] as const, claimHistory: (id: string) => ['claims', id, 'history'] as const },
}));

function renderSimulation() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <RoleSimulationProvider>
        <MemoryRouter>
          <Simulation />
        </MemoryRouter>
      </RoleSimulationProvider>
    </QueryClientProvider>
  );
}

describe('Simulation', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('renders RoleSelectLanding when role is adjuster', () => {
    localStorage.setItem('simulation_role', 'adjuster');
    renderSimulation();
    expect(screen.getByRole('heading', { name: 'Role Simulation' })).toBeInTheDocument();
    expect(screen.getByText(/Experience the claims system from different perspectives/)).toBeInTheDocument();
  });

  it('renders CustomerPortal when role is customer', () => {
    localStorage.setItem('simulation_role', 'customer');
    renderSimulation();
    expect(screen.getByRole('heading', { name: 'My Claims' })).toBeInTheDocument();
  });

  it('renders RepairShopPortal when role is repair_shop', () => {
    localStorage.setItem('simulation_role', 'repair_shop');
    renderSimulation();
    expect(screen.getByRole('heading', { name: 'Repair Jobs' })).toBeInTheDocument();
  });

  it('renders ThirdPartyPortal when role is third_party', () => {
    localStorage.setItem('simulation_role', 'third_party');
    renderSimulation();
    expect(screen.getByRole('heading', { name: 'Cross-Carrier Claims' })).toBeInTheDocument();
  });
});
