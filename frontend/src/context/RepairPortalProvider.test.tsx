import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, beforeEach } from 'vitest';
import { RepairPortalProvider } from './RepairPortalProvider';
import { useRepairPortal } from './useRepairPortal';
import { clearRepairPortalSession, getRepairPortalSession } from '../api/repairPortalClient';

function TestConsumer() {
  const { session, isAuthenticated, login, logout } = useRepairPortal();
  return (
    <div>
      <span data-testid="auth">{isAuthenticated ? 'yes' : 'no'}</span>
      <span data-testid="claim">{session?.claimId ?? 'none'}</span>
      <button onClick={() => login({ claimId: 'CLM-1', token: 'tok' })}>login</button>
      <button onClick={() => logout()}>logout</button>
    </div>
  );
}

describe('RepairPortalProvider', () => {
  beforeEach(() => {
    clearRepairPortalSession();
  });

  it('starts unauthenticated', () => {
    render(
      <RepairPortalProvider>
        <TestConsumer />
      </RepairPortalProvider>
    );
    expect(screen.getByTestId('auth').textContent).toBe('no');
    expect(screen.getByTestId('claim').textContent).toBe('none');
  });

  it('login sets session and marks authenticated', () => {
    render(
      <RepairPortalProvider>
        <TestConsumer />
      </RepairPortalProvider>
    );

    act(() => {
      fireEvent.click(screen.getByText('login'));
    });

    expect(screen.getByTestId('auth').textContent).toBe('yes');
    expect(screen.getByTestId('claim').textContent).toBe('CLM-1');
    expect(getRepairPortalSession()).toEqual({ claimId: 'CLM-1', token: 'tok' });
  });

  it('logout clears session', () => {
    render(
      <RepairPortalProvider>
        <TestConsumer />
      </RepairPortalProvider>
    );

    act(() => {
      fireEvent.click(screen.getByText('login'));
    });
    act(() => {
      fireEvent.click(screen.getByText('logout'));
    });

    expect(screen.getByTestId('auth').textContent).toBe('no');
    expect(getRepairPortalSession()).toBeNull();
  });
});
