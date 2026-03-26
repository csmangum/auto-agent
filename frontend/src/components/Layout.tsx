import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { useState, useRef, useEffect, useCallback } from 'react';
import AuthControl from './AuthControl';
import ChatPanel from './ChatPanel';
import RoleSwitcher from './RoleSwitcher';
import SimulationBanner from './SimulationBanner';
import ThemeToggle from './ThemeToggle';
import Breadcrumbs from './Breadcrumbs';
import { useBreadcrumbs } from '../hooks/useBreadcrumbs';
import { DocumentIcon } from './icons';
import { NAV_ICONS, type NavIconKey } from './icons/icons-maps';
import { useRoleSimulation } from '../context/RoleSimulationContext';
import ClaimBreadcrumbLabelProvider from '../context/ClaimBreadcrumbLabelProvider';
import { useClaimBreadcrumbLabel } from '../hooks/useClaimBreadcrumbLabel';

interface NavItem {
  to: string;
  label: string;
  icon: NavIconKey;
  end?: boolean;
}

const MAIN_NAV: NavItem[] = [
  { to: '/dashboard', label: 'Dashboard', icon: 'dashboard', end: true },
  { to: '/claims', label: 'Claims', icon: 'claims' },
  { to: '/claims/new', label: 'New Claim', icon: 'newClaim' },
];

const REFERENCE_NAV: NavItem[] = [
  { to: '/docs', label: 'Documentation', icon: 'docs' },
  { to: '/skills', label: 'Skills', icon: 'skills' },
  { to: '/agents', label: 'Agents & Crews', icon: 'agents' },
  { to: '/cost', label: 'LLM Cost', icon: 'cost' },
  { to: '/system', label: 'System Config', icon: 'system' },
  { to: '/system/templates', label: 'Note Templates', icon: 'noteTemplates' },
];

const WORKBENCH_NAV: NavItem[] = [
  { to: '/workbench', label: 'My Workbench', icon: 'workbench' },
  { to: '/workbench/queue', label: 'Assignment Queue', icon: 'queue' },
  { to: '/workbench/diary', label: 'Diary / Calendar', icon: 'diary' },
];

const SIMULATION_NAV: NavItem[] = [
  { to: '/simulate', label: 'Role Simulation', icon: 'simulate' },
];

function NavSection({ label, items, onLinkClick }: { label: string; items: NavItem[]; onLinkClick: () => void }) {
  return (
    <div>
      <p className="px-3 mb-2 text-[11px] font-semibold uppercase tracking-wider text-gray-500">
        {label}
      </p>
      <div className="space-y-0.5">
        {items.map((item) => {
          const Icon = NAV_ICONS[item.icon] ?? DocumentIcon;
          return (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={onLinkClick}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-all duration-150 ${
                isActive
                  ? 'bg-blue-600/15 text-blue-400 shadow-sm shadow-blue-500/5'
                  : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
              }`
            }
          >
            <span className="shrink-0 flex items-center justify-center text-current">
              <Icon className="w-5 h-5" />
            </span>
            {item.label}
          </NavLink>
          );
        })}
      </div>
    </div>
  );
}

function LayoutShell() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const closeSidebar = () => {
    setSidebarOpen(false);
    window.setTimeout(() => menuButtonRef.current?.focus(), 0);
  };
  const openSidebar = () => setSidebarOpen(true);
  const { roleDef, isSimulating } = useRoleSimulation();
  const { pathname } = useLocation();
  const claimBreadcrumbLabel = useClaimBreadcrumbLabel();
  const breadcrumbItems = useBreadcrumbs(claimBreadcrumbLabel);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const sidebarRef = useRef<HTMLElement>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);
  const [isNarrowViewport, setIsNarrowViewport] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia('(max-width: 1023px)');
    setIsNarrowViewport(mq.matches);
    const onChange = () => setIsNarrowViewport(mq.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  const brandBg = isSimulating ? roleDef.accentBg : 'bg-blue-600';
  const brandShadow = isSimulating ? '' : 'shadow-lg shadow-blue-600/20';

  const trapFocus = useCallback(
    (e: KeyboardEvent) => {
      if (!sidebarOpen) return;
      if (e.key !== 'Tab') return;
      const root = sidebarRef.current;
      if (!root) return;
      const focusables = root.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
      const list = Array.from(focusables).filter((el) => el.offsetParent !== null || el === document.activeElement);
      if (list.length === 0) return;
      const first = list[0];
      const last = list[list.length - 1];
      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last.focus();
        }
      } else if (document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    },
    [sidebarOpen]
  );

  useEffect(() => {
    if (!sidebarOpen) return;
    previouslyFocusedRef.current = (document.activeElement as HTMLElement) ?? null;
    const t = window.setTimeout(() => {
      sidebarRef.current?.querySelector<HTMLElement>('a[href], button')?.focus();
    }, 0);
    document.addEventListener('keydown', trapFocus);
    return () => {
      window.clearTimeout(t);
      document.removeEventListener('keydown', trapFocus);
      previouslyFocusedRef.current?.focus?.();
    };
  }, [sidebarOpen, trapFocus]);

  const showBreadcrumbs =
    breadcrumbItems.length > 1 &&
    pathname !== '/' &&
    pathname !== '/dashboard' &&
    pathname !== '/workbench';

  return (
    <div className="min-h-screen bg-gray-950 flex">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:top-3 focus:left-3 focus:z-[100] focus:px-4 focus:py-2 focus:bg-blue-600 focus:text-white focus:rounded-lg focus:shadow-lg focus:outline-none"
      >
        Skip to main content
      </a>

      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          data-testid="sidebar-overlay"
          className="fixed inset-0 bg-black/60 backdrop-blur-sm z-20 lg:hidden"
          onClick={closeSidebar}
          aria-hidden
        />
      )}

      {/* Sidebar */}
      <aside
        ref={sidebarRef}
        id="app-sidebar"
        // When drawer is closed on mobile, remove from tab order / AT (desktop sidebar stays usable)
        inert={isNarrowViewport && !sidebarOpen ? true : undefined}
        className={`fixed lg:static inset-y-0 left-0 z-30 w-64 bg-gray-900 border-r border-gray-800 transform transition-transform duration-200 lg:translate-x-0 flex flex-col ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {/* Brand */}
        <div className="p-5 border-b border-gray-800">
          <div className="flex items-center gap-3">
            <div className={`w-8 h-8 rounded-lg ${brandBg} flex items-center justify-center text-white text-sm font-bold ${brandShadow}`}>
              C
            </div>
            <div className="min-w-0">
              <h1 className="text-sm font-bold text-gray-100 truncate">Claims System</h1>
              <p className="text-[11px] text-gray-500 truncate">Claims Management Platform</p>
            </div>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 p-3 space-y-6 overflow-y-auto">
          <NavSection label="Main" items={MAIN_NAV} onLinkClick={closeSidebar} />
          <NavSection label="Workbench" items={WORKBENCH_NAV} onLinkClick={closeSidebar} />
          <NavSection label="Simulation" items={SIMULATION_NAV} onLinkClick={closeSidebar} />
          <NavSection label="Reference" items={REFERENCE_NAV} onLinkClick={closeSidebar} />
        </nav>

        {/* Footer */}
        <div className="p-4 border-t border-gray-800 space-y-3">
          <RoleSwitcher />
          <AuthControl />
          <ThemeToggle />
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono font-medium bg-gray-800 text-gray-500 ring-1 ring-gray-700">
              v0.1.0
            </span>
            <span className="text-[11px] text-gray-600">CrewAI + Python</span>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Simulation banner */}
        <SimulationBanner />

        {/* Mobile top bar */}
        <header className="bg-gray-900 border-b border-gray-800 px-4 py-3 flex items-center justify-between gap-4 lg:hidden">
          <div className="flex items-center gap-3">
            <button
              ref={menuButtonRef}
              type="button"
              onClick={openSidebar}
              aria-label="Open menu"
              aria-expanded={sidebarOpen}
              aria-controls="app-sidebar"
              className="text-gray-400 hover:text-gray-200 transition-colors"
            >
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
            <div className={`w-7 h-7 rounded-lg ${brandBg} flex items-center justify-center text-white text-xs font-bold`}>
              C
            </div>
            <h1 className="text-sm font-semibold text-gray-100">Claims System</h1>
          </div>
          <AuthControl />
        </header>

        <main id="main-content" tabIndex={-1} className="flex-1 p-6 overflow-auto outline-none">
          {showBreadcrumbs ? <Breadcrumbs items={breadcrumbItems} /> : null}
          <Outlet />
        </main>
      </div>

      {/* Chat assistant (floating panel) */}
      <ChatPanel />
    </div>
  );
}

export default function Layout() {
  return (
    <ClaimBreadcrumbLabelProvider>
      <LayoutShell />
    </ClaimBreadcrumbLabelProvider>
  );
}
