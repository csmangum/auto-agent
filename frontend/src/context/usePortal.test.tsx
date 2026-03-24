import { renderHook } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { usePortal } from './usePortal';
import { PortalContext } from './portalContext';
import type { PortalContextValue } from './portalContext';

describe('usePortal', () => {
  it('throws when used outside PortalProvider', () => {
    expect(() => renderHook(() => usePortal())).toThrow(
      'usePortal must be used within PortalProvider'
    );
  });

  it('returns context value when inside provider', () => {
    const value: PortalContextValue = {
      session: { token: 'tok' },
      isAuthenticated: true,
      login: () => {},
      logout: () => {},
    };

    const { result } = renderHook(() => usePortal(), {
      wrapper: ({ children }) => (
        <PortalContext.Provider value={value}>{children}</PortalContext.Provider>
      ),
    });

    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.session?.token).toBe('tok');
  });
});
