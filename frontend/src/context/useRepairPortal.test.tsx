import { renderHook } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { useRepairPortal } from './useRepairPortal';
import { RepairPortalContext } from './repairPortalContext';
import type { RepairPortalContextValue } from './repairPortalContext';

describe('useRepairPortal', () => {
  it('throws when used outside RepairPortalProvider', () => {
    expect(() => renderHook(() => useRepairPortal())).toThrow(
      'useRepairPortal must be used within RepairPortalProvider'
    );
  });

  it('returns context value when inside provider', () => {
    const value: RepairPortalContextValue = {
      session: { claimId: 'CLM-1', token: 'tok' },
      isAuthenticated: true,
      login: () => {},
      logout: () => {},
    };

    const { result } = renderHook(() => useRepairPortal(), {
      wrapper: ({ children }) => (
        <RepairPortalContext.Provider value={value}>{children}</RepairPortalContext.Provider>
      ),
    });

    expect(result.current.isAuthenticated).toBe(true);
  });
});
