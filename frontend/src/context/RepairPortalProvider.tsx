import { useCallback, useEffect, useState } from 'react';
import {
  getRepairPortalSession,
  setRepairPortalSession,
  clearRepairPortalSession,
  type RepairPortalSession,
} from '../api/repairPortalClient';
import { RepairPortalContext } from './repairPortalContext';

export function RepairPortalProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<RepairPortalSession | null>(() =>
    getRepairPortalSession()
  );

  useEffect(() => {
    setSession(getRepairPortalSession());
  }, []);

  const login = useCallback((s: RepairPortalSession) => {
    setRepairPortalSession(s);
    setSession(s);
  }, []);

  const logout = useCallback(() => {
    clearRepairPortalSession();
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
    <RepairPortalContext.Provider value={value}>{children}</RepairPortalContext.Provider>
  );
}
