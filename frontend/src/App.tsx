import { Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import ErrorBoundary from './components/ErrorBoundary';
import { PortalProvider } from './context/PortalContext';
import { RepairPortalProvider } from './context/RepairPortalProvider';
import { ThirdPartyPortalProvider } from './context/ThirdPartyPortalProvider';
import PortalGuard from './components/PortalGuard';
import RepairPortalGuard from './components/RepairPortalGuard';
import ThirdPartyPortalGuard from './components/ThirdPartyPortalGuard';
import Dashboard from './pages/Dashboard';
import ClaimsList from './pages/ClaimsList';
import ClaimDetail from './pages/ClaimDetail';
import NewClaimForm from './pages/NewClaimForm';
import Documentation from './pages/Documentation';
import Skills from './pages/Skills';
import SkillDetail from './pages/SkillDetail';
import Agents from './pages/Agents';
import SystemConfig from './pages/SystemConfig';
import CostDashboard from './pages/CostDashboard';
import Simulation from './pages/Simulation';
import WorkbenchDashboard from './pages/WorkbenchDashboard';
import AssignmentQueue from './pages/AssignmentQueue';
import DiaryCalendar from './pages/DiaryCalendar';
import PortalLogin from './pages/PortalLogin';
import PortalClaimsList from './pages/PortalClaimsList';
import PortalClaimDetail from './pages/PortalClaimDetail';
import RepairPortalLogin from './pages/RepairPortalLogin';
import RepairPortalClaimDetail from './pages/RepairPortalClaimDetail';
import ThirdPartyPortalLogin from './pages/ThirdPartyPortalLogin';
import ThirdPartyPortalClaimDetail from './pages/ThirdPartyPortalClaimDetail';
import NotFound from './pages/NotFound';
import { useRoleSimulation } from './context/RoleSimulationContext';

// Uses the client-side simulation role (UI persona) — not the backend identity
// from /auth/me — to decide the landing page per simulated persona.
function HomeLanding() {
  const { role } = useRoleSimulation();
  if (role === 'adjuster') {
    return <Navigate to="/workbench" replace />;
  }
  return <Dashboard />;
}

export default function App() {
  return (
    <ErrorBoundary>
      <PortalProvider>
        <RepairPortalProvider>
        <ThirdPartyPortalProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<HomeLanding />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/claims" element={<ClaimsList />} />
            <Route path="/claims/new" element={<NewClaimForm />} />
            <Route path="/claims/:claimId" element={<ClaimDetail />} />
            <Route path="/workbench" element={<WorkbenchDashboard />} />
            <Route path="/workbench/queue" element={<AssignmentQueue />} />
            <Route path="/workbench/diary" element={<DiaryCalendar />} />
            <Route path="/simulate" element={<Simulation />} />
            <Route path="/docs" element={<Documentation />} />
            <Route path="/docs/:slug" element={<Documentation />} />
            <Route path="/skills" element={<Skills />} />
            <Route path="/skills/:name" element={<SkillDetail />} />
            <Route path="/agents" element={<Agents />} />
            <Route path="/cost" element={<CostDashboard />} />
            <Route path="/system" element={<SystemConfig />} />
            <Route path="*" element={<NotFound />} />
          </Route>
          <Route path="/portal">
            <Route path="login" element={<PortalLogin />} />
            <Route
              path="claims"
              element={
                <PortalGuard>
                  <PortalClaimsList />
                </PortalGuard>
              }
            />
            <Route
              path="claims/:claimId"
              element={
                <PortalGuard>
                  <PortalClaimDetail />
                </PortalGuard>
              }
            />
            <Route path="" element={<Navigate to="/portal/login" replace />} />
          </Route>
          <Route path="/repair-portal">
            <Route path="login" element={<RepairPortalLogin />} />
            <Route
              path="claims/:claimId"
              element={
                <RepairPortalGuard>
                  <RepairPortalClaimDetail />
                </RepairPortalGuard>
              }
            />
            <Route path="" element={<Navigate to="/repair-portal/login" replace />} />
          </Route>
          <Route path="/third-party-portal">
            <Route path="login" element={<ThirdPartyPortalLogin />} />
            <Route
              path="claims/:claimId"
              element={
                <ThirdPartyPortalGuard>
                  <ThirdPartyPortalClaimDetail />
                </ThirdPartyPortalGuard>
              }
            />
            <Route path="" element={<Navigate to="/third-party-portal/login" replace />} />
          </Route>
        </Routes>
        </ThirdPartyPortalProvider>
        </RepairPortalProvider>
      </PortalProvider>
    </ErrorBoundary>
  );
}
