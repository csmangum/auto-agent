import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from 'react';
import {
  getPortalSession,
  setPortalSession,
  clearPortalSession,
  type PortalSession,
} from '../api/portalClient';

interface PortalContextValue {
  session: PortalSession | null;
  isAuthenticated: boolean;
  login: (s: PortalSession) => void;
  logout: () => void;
}

const PortalContext = createContext<PortalContextValue | null>(null);

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

  const value: PortalContextValue = {
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

export function usePortal() {
  const ctx = useContext(PortalContext);
  if (!ctx) throw new Error('usePortal must be used within PortalProvider');
  return ctx;
}
