import { Navigate, useLocation } from 'react-router-dom';
import { useThirdPartyPortal } from '../context/useThirdPartyPortal';

/** Redirects to /third-party-portal/login if not authenticated. */
export default function ThirdPartyPortalGuard({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useThirdPartyPortal();
  const location = useLocation();

  if (!isAuthenticated) {
    return (
      <Navigate to="/third-party-portal/login" state={{ from: location }} replace />
    );
  }

  return <>{children}</>;
}
