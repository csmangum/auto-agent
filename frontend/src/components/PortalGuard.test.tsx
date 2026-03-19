import { render, screen } from '@testing-library/react';
import { describe, it, expect, beforeEach } from 'vitest';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { PortalProvider } from '../context/PortalContext';
import { setPortalSession, clearPortalSession } from '../api/portalClient';
import PortalGuard from './PortalGuard';

function createWrapper(initialPath = '/portal/claims') {
  return function Wrapper({ children: _children }: { children: React.ReactNode }) {
    return (
      <PortalProvider>
        <MemoryRouter initialEntries={[initialPath]}>
          <Routes>
            <Route
              path="/portal/claims"
              element={
                <PortalGuard>
                  <div data-testid="protected-content">Protected</div>
                </PortalGuard>
              }
            />
            <Route path="/portal/login" element={<div data-testid="login-page">Login</div>} />
          </Routes>
        </MemoryRouter>
      </PortalProvider>
    );
  };
}

describe('PortalGuard', () => {
  const Wrapper = createWrapper();

  beforeEach(() => {
    clearPortalSession();
  });

  it('redirects to /portal/login when not authenticated', () => {
    render(<Wrapper>{null}</Wrapper>);
    expect(screen.getByTestId('login-page')).toBeInTheDocument();
    expect(screen.queryByTestId('protected-content')).not.toBeInTheDocument();
  });

  it('renders children when authenticated', () => {
    setPortalSession({ token: 'test-token' });
    render(<Wrapper>{null}</Wrapper>);
    expect(screen.getByTestId('protected-content')).toBeInTheDocument();
    expect(screen.getByText('Protected')).toBeInTheDocument();
    expect(screen.queryByTestId('login-page')).not.toBeInTheDocument();
  });
});
