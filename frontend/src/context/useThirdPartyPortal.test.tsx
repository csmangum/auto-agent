import { renderHook } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { useThirdPartyPortal } from './useThirdPartyPortal';
import { ThirdPartyPortalContext } from './thirdPartyPortalContext';
import type { ThirdPartyPortalContextValue } from './thirdPartyPortalContext';

describe('useThirdPartyPortal', () => {
  it('throws when used outside ThirdPartyPortalProvider', () => {
    expect(() => renderHook(() => useThirdPartyPortal())).toThrow(
      'useThirdPartyPortal must be used within ThirdPartyPortalProvider'
    );
  });

  it('returns context value when inside provider', () => {
    const value: ThirdPartyPortalContextValue = {
      session: { claimId: 'CLM-2', token: 'tok' },
      isAuthenticated: true,
      login: () => {},
      logout: () => {},
    };

    const { result } = renderHook(() => useThirdPartyPortal(), {
      wrapper: ({ children }) => (
        <ThirdPartyPortalContext.Provider value={value}>
          {children}
        </ThirdPartyPortalContext.Provider>
      ),
    });

    expect(result.current.isAuthenticated).toBe(true);
  });
});
