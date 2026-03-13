import { Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import ErrorBoundary from './components/ErrorBoundary';
import Dashboard from './pages/Dashboard';
import ClaimsList from './pages/ClaimsList';
import ClaimDetail from './pages/ClaimDetail';
import NewClaimForm from './pages/NewClaimForm';
import Documentation from './pages/Documentation';
import Skills from './pages/Skills';
import SkillDetail from './pages/SkillDetail';
import Agents from './pages/Agents';
import SystemConfig from './pages/SystemConfig';
import Simulation from './pages/Simulation';
import NotFound from './pages/NotFound';

export default function App() {
  return (
    <ErrorBoundary>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/claims" element={<ClaimsList />} />
          <Route path="/claims/new" element={<NewClaimForm />} />
          <Route path="/claims/:claimId" element={<ClaimDetail />} />
          <Route path="/simulate" element={<Simulation />} />
          <Route path="/docs" element={<Documentation />} />
          <Route path="/docs/:slug" element={<Documentation />} />
          <Route path="/skills" element={<Skills />} />
          <Route path="/skills/:name" element={<SkillDetail />} />
          <Route path="/agents" element={<Agents />} />
          <Route path="/system" element={<SystemConfig />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </ErrorBoundary>
  );
}
