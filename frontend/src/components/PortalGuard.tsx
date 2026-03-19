import { Navigate, useLocation } from 'react-router-dom';
import { usePortal } from '../context/usePortal';

/** Redirects to /portal/login if not authenticated. */
export default function PortalGuard({
  children,
}: {
  children: React.ReactNode;
}) {
  const { isAuthenticated } = usePortal();
  const location = useLocation();

  if (!isAuthenticated) {
    return (
      <Navigate
        to="/portal/login"
        state={{ from: location }}
        replace
      />
    );
  }

  return <>{children}</>;
}
