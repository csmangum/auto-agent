import { NavLink, Outlet } from 'react-router-dom';
import { useState } from 'react';
import AuthControl from './AuthControl';

const MAIN_NAV = [
  { to: '/', label: 'Dashboard', icon: '📊' },
  { to: '/claims', label: 'Claims', icon: '📋' },
  { to: '/claims/new', label: 'New Claim', icon: '➕' },
];

const REFERENCE_NAV = [
  { to: '/docs', label: 'Documentation', icon: '📖' },
  { to: '/skills', label: 'Skills', icon: '🧠' },
  { to: '/agents', label: 'Agents & Crews', icon: '🤖' },
  { to: '/system', label: 'System Config', icon: '⚙️' },
];

function NavSection({ label, items, onLinkClick }: { label: string; items: typeof MAIN_NAV; onLinkClick: () => void }) {
  return (
    <div>
      <p className="px-3 mb-2 text-[11px] font-semibold uppercase tracking-wider text-gray-500">
        {label}
      </p>
      <div className="space-y-0.5">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            onClick={onLinkClick}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-all duration-150 ${
                isActive
                  ? 'bg-blue-600/15 text-blue-400 shadow-sm shadow-blue-500/5'
                  : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
              }`
            }
          >
            <span className="text-base shrink-0">{item.icon}</span>
            {item.label}
          </NavLink>
        ))}
      </div>
    </div>
  );
}

export default function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const closeSidebar = () => setSidebarOpen(false);

  return (
    <div className="min-h-screen bg-gray-950 flex">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/60 backdrop-blur-sm z-20 lg:hidden"
          onClick={closeSidebar}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`fixed lg:static inset-y-0 left-0 z-30 w-64 bg-gray-900 border-r border-gray-800 transform transition-transform duration-200 lg:translate-x-0 flex flex-col ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {/* Brand */}
        <div className="p-5 border-b border-gray-800">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center text-white text-sm font-bold shadow-lg shadow-blue-600/20">
              C
            </div>
            <div className="min-w-0">
              <h1 className="text-sm font-bold text-gray-100 truncate">Claims System</h1>
              <p className="text-[11px] text-gray-500 truncate">Observability Dashboard</p>
            </div>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 p-3 space-y-6 overflow-y-auto">
          <NavSection label="Main" items={MAIN_NAV} onLinkClick={closeSidebar} />
          <NavSection label="Reference" items={REFERENCE_NAV} onLinkClick={closeSidebar} />
        </nav>

        {/* Footer */}
        <div className="p-4 border-t border-gray-800">
          <AuthControl />
          <div className="mt-3 flex items-center gap-2">
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono font-medium bg-gray-800 text-gray-500 ring-1 ring-gray-700">
              v0.1.0
            </span>
            <span className="text-[11px] text-gray-600">CrewAI + Python</span>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Mobile top bar */}
        <header className="bg-gray-900 border-b border-gray-800 px-4 py-3 flex items-center justify-between gap-4 lg:hidden">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setSidebarOpen(true)}
              aria-label="Open menu"
              aria-expanded={sidebarOpen}
              className="text-gray-400 hover:text-gray-200 transition-colors"
            >
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
            <div className="w-7 h-7 rounded-lg bg-blue-600 flex items-center justify-center text-white text-xs font-bold">
              C
            </div>
            <h1 className="text-sm font-semibold text-gray-100">Claims System</h1>
          </div>
          <AuthControl />
        </header>

        <main className="flex-1 p-6 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
