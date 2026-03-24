import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, beforeEach } from 'vitest';
import { ThirdPartyPortalProvider } from './ThirdPartyPortalProvider';
import { useThirdPartyPortal } from './useThirdPartyPortal';
import {
  clearThirdPartyPortalSession,
  getThirdPartyPortalSession,
} from '../api/thirdPartyPortalClient';

function TestConsumer() {
  const { session, isAuthenticated, login, logout } = useThirdPartyPortal();
  return (
    <div>
      <span data-testid="auth">{isAuthenticated ? 'yes' : 'no'}</span>
      <span data-testid="claim">{session?.claimId ?? 'none'}</span>
      <button onClick={() => login({ claimId: 'CLM-2', token: 'tp-tok' })}>login</button>
      <button onClick={() => logout()}>logout</button>
    </div>
  );
}

describe('ThirdPartyPortalProvider', () => {
  beforeEach(() => {
    clearThirdPartyPortalSession();
  });

  it('starts unauthenticated', () => {
    render(
      <ThirdPartyPortalProvider>
        <TestConsumer />
      </ThirdPartyPortalProvider>
    );
    expect(screen.getByTestId('auth').textContent).toBe('no');
  });

  it('login sets session', () => {
    render(
      <ThirdPartyPortalProvider>
        <TestConsumer />
      </ThirdPartyPortalProvider>
    );

    act(() => {
      fireEvent.click(screen.getByText('login'));
    });

    expect(screen.getByTestId('auth').textContent).toBe('yes');
    expect(screen.getByTestId('claim').textContent).toBe('CLM-2');
    expect(getThirdPartyPortalSession()).toEqual({ claimId: 'CLM-2', token: 'tp-tok' });
  });

  it('logout clears session', () => {
    render(
      <ThirdPartyPortalProvider>
        <TestConsumer />
      </ThirdPartyPortalProvider>
    );

    act(() => fireEvent.click(screen.getByText('login')));
    act(() => fireEvent.click(screen.getByText('logout')));

    expect(screen.getByTestId('auth').textContent).toBe('no');
    expect(getThirdPartyPortalSession()).toBeNull();
  });
});
