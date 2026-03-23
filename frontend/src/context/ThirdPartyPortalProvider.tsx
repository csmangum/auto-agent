import { useCallback, useEffect, useState } from 'react';
import {
  getThirdPartyPortalSession,
  setThirdPartyPortalSession,
  clearThirdPartyPortalSession,
  type ThirdPartyPortalSession,
} from '../api/thirdPartyPortalClient';
import { ThirdPartyPortalContext } from './thirdPartyPortalContext';

export function ThirdPartyPortalProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<ThirdPartyPortalSession | null>(() =>
    getThirdPartyPortalSession()
  );

  useEffect(() => {
    setSession(getThirdPartyPortalSession());
  }, []);

  const login = useCallback((s: ThirdPartyPortalSession) => {
    setThirdPartyPortalSession(s);
    setSession(s);
  }, []);

  const logout = useCallback(() => {
    clearThirdPartyPortalSession();
    setSession(null);
  }, []);

  const value = {
    session,
    isAuthenticated: !!(
      session &&
      session.token &&
      session.token.length > 0 &&
      session.claimId &&
      session.claimId.length > 0
    ),
    login,
    logout,
  };

  return (
    <ThirdPartyPortalContext.Provider value={value}>{children}</ThirdPartyPortalContext.Provider>
  );
}
