import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from './context/AuthContext';
import { RoleSimulationProvider } from './context/RoleSimulationContext';
import App from './App';

vi.mock('./api/queries', () => ({
  useClaimsStats: vi.fn(() => ({ data: { total_claims: 0, by_status: {}, by_type: {} }, isLoading: false, error: null })),
  useClaims: vi.fn(() => ({ data: { claims: [], total: 0 }, isLoading: false, error: null })),
  useClaim: vi.fn(() => ({ data: null, isLoading: false, error: null })),
  useClaimHistory: vi.fn(() => ({ data: null, isLoading: false, error: null })),
  useClaimWorkflows: vi.fn(() => ({ data: null, isLoading: false, error: null })),
  useDocs: vi.fn(() => ({ data: { pages: [] }, isLoading: false, error: null })),
  useDoc: vi.fn(() => ({ data: null, isLoading: false, error: null })),
  useSkills: vi.fn(() => ({ data: { groups: {} }, isLoading: false, error: null })),
  useSkill: vi.fn(() => ({ data: null, isLoading: false, error: null })),
  useSystemConfig: vi.fn(() => ({
    data: { escalation: {}, fraud: {}, crew_verbose: false },
    isLoading: false,
    error: null,
  })),
  useSystemHealth: vi.fn(() => ({
    data: { status: 'healthy', database: 'sqlite', total_claims: 0 },
    isLoading: false,
    error: null,
  })),
  useAgentsCatalog: vi.fn(() => ({ data: { crews: [] }, isLoading: false, error: null })),
}));

function renderApp(initialPath = '/') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <RoleSimulationProvider>
          <MemoryRouter initialEntries={[initialPath]}>
            <App />
          </MemoryRouter>
        </RoleSimulationProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}

describe('App', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders layout with navigation', () => {
    renderApp();
    expect(screen.getAllByText('Claims System').length).toBeGreaterThanOrEqual(1);
  });

  it('renders 404 for unknown route', () => {
    renderApp('/unknown-path');
    expect(screen.getByText('404')).toBeInTheDocument();
    expect(screen.getByText('Page not found')).toBeInTheDocument();
  });

  it('renders Dashboard at /', () => {
    renderApp('/');
    expect(screen.getByRole('heading', { name: 'Dashboard' })).toBeInTheDocument();
  });

  it('renders Claims list at /claims', () => {
    renderApp('/claims');
    expect(screen.getByRole('heading', { name: 'Claims' })).toBeInTheDocument();
  });

  it('renders New Claim form at /claims/new', () => {
    renderApp('/claims/new');
    expect(screen.getByRole('heading', { name: 'New Claim' })).toBeInTheDocument();
  });

  it('renders Documentation at /docs', () => {
    renderApp('/docs');
    expect(screen.getByRole('heading', { name: 'Documentation' })).toBeInTheDocument();
  });

  it('renders Skills at /skills', () => {
    renderApp('/skills');
    expect(screen.getByRole('heading', { name: 'Agent Skills' })).toBeInTheDocument();
  });

  it('renders Agents at /agents', () => {
    renderApp('/agents');
    expect(screen.getByRole('heading', { name: 'Agents & Crews' })).toBeInTheDocument();
  });

  it('renders System Config at /system', () => {
    renderApp('/system');
    expect(screen.getByRole('heading', { name: 'System Configuration' })).toBeInTheDocument();
  });

  it('renders Simulation landing at /simulate with no role set', () => {
    renderApp('/simulate');
    expect(screen.getByRole('heading', { name: 'Role Simulation' })).toBeInTheDocument();
  });
});
