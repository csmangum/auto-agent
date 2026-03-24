import { render, screen } from '@testing-library/react';
import { describe, it, expect, beforeEach } from 'vitest';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { ThirdPartyPortalProvider } from '../context/ThirdPartyPortalProvider';
import {
  setThirdPartyPortalSession,
  clearThirdPartyPortalSession,
} from '../api/thirdPartyPortalClient';
import ThirdPartyPortalGuard from './ThirdPartyPortalGuard';

function renderWithRouter(initialPath = '/third-party-portal/claims') {
  return render(
    <ThirdPartyPortalProvider>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route
            path="/third-party-portal/claims"
            element={
              <ThirdPartyPortalGuard>
                <div data-testid="protected">Protected</div>
              </ThirdPartyPortalGuard>
            }
          />
          <Route
            path="/third-party-portal/login"
            element={<div data-testid="login">Login</div>}
          />
        </Routes>
      </MemoryRouter>
    </ThirdPartyPortalProvider>
  );
}

describe('ThirdPartyPortalGuard', () => {
  beforeEach(() => {
    clearThirdPartyPortalSession();
  });

  it('redirects to login when not authenticated', () => {
    renderWithRouter();
    expect(screen.getByTestId('login')).toBeInTheDocument();
    expect(screen.queryByTestId('protected')).not.toBeInTheDocument();
  });

  it('renders children when authenticated', () => {
    setThirdPartyPortalSession({ claimId: 'CLM-2', token: 'tok' });
    renderWithRouter();
    expect(screen.getByTestId('protected')).toBeInTheDocument();
    expect(screen.queryByTestId('login')).not.toBeInTheDocument();
  });
});
