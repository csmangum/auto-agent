import { useContext } from 'react';
import { ThirdPartyPortalContext } from './thirdPartyPortalContext';

export function useThirdPartyPortal() {
  const ctx = useContext(ThirdPartyPortalContext);
  if (!ctx) {
    throw new Error('useThirdPartyPortal must be used within ThirdPartyPortalProvider');
  }
  return ctx;
}
