import { render, screen } from '@testing-library/react';
import { describe, it, expect, beforeEach } from 'vitest';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { RepairPortalProvider } from '../context/RepairPortalProvider';
import { setRepairPortalSession, clearRepairPortalSession } from '../api/repairPortalClient';
import RepairPortalGuard from './RepairPortalGuard';

function renderWithRouter(initialPath = '/repair-portal/claims') {
  return render(
    <RepairPortalProvider>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route
            path="/repair-portal/claims"
            element={
              <RepairPortalGuard>
                <div data-testid="protected">Protected</div>
              </RepairPortalGuard>
            }
          />
          <Route
            path="/repair-portal/login"
            element={<div data-testid="login">Login</div>}
          />
        </Routes>
      </MemoryRouter>
    </RepairPortalProvider>
  );
}

describe('RepairPortalGuard', () => {
  beforeEach(() => {
    clearRepairPortalSession();
  });

  it('redirects to login when not authenticated', () => {
    renderWithRouter();
    expect(screen.getByTestId('login')).toBeInTheDocument();
    expect(screen.queryByTestId('protected')).not.toBeInTheDocument();
  });

  it('renders children when authenticated', () => {
    setRepairPortalSession({ claimId: 'CLM-1', token: 'tok' });
    renderWithRouter();
    expect(screen.getByTestId('protected')).toBeInTheDocument();
    expect(screen.queryByTestId('login')).not.toBeInTheDocument();
  });
});
