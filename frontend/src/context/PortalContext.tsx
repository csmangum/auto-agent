import { useCallback, useEffect, useState } from 'react';
import {
  getPortalSession,
  setPortalSession,
  clearPortalSession,
  type PortalSession,
} from '../api/portalClient';
import { PortalContext } from './portalContext';

export function PortalProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<PortalSession | null>(() =>
    getPortalSession()
  );

  useEffect(() => {
    setSession(getPortalSession());
  }, []);

  const login = useCallback((s: PortalSession) => {
    setPortalSession(s);
    setSession(s);
  }, []);

  const logout = useCallback(() => {
    clearPortalSession();
    setSession(null);
  }, []);

  const value = {
    session,
    isAuthenticated: !!(
      session &&
      ((session.token && session.token.length > 0) ||
        (session.policyNumber && session.vin) ||
        (session.email && session.email.length > 0))
    ),
    login,
    logout,
  };

  return (
    <PortalContext.Provider value={value}>{children}</PortalContext.Provider>
  );
}
