import { Navigate, useLocation } from 'react-router-dom';
import { useRepairPortal } from '../context/useRepairPortal';

/** Redirects to /repair-portal/login if not authenticated. */
export default function RepairPortalGuard({
  children,
}: {
  children: React.ReactNode;
}) {
  const { isAuthenticated } = useRepairPortal();
  const location = useLocation();

  if (!isAuthenticated) {
    return (
      <Navigate
        to="/repair-portal/login"
        state={{ from: location }}
        replace
      />
    );
  }

  return <>{children}</>;
}
