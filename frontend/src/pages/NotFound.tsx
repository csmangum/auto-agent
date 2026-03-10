import { Link } from 'react-router-dom';

const QUICK_LINKS = [
  { to: '/', label: 'Dashboard', icon: '📊' },
  { to: '/claims', label: 'Claims', icon: '📋' },
  { to: '/docs', label: 'Documentation', icon: '📖' },
  { to: '/agents', label: 'Agents', icon: '🤖' },
];

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[500px] p-8 animate-fade-in">
      <div className="text-8xl mb-6 opacity-30">🔍</div>
      <h1 className="text-5xl font-bold text-gray-200 mb-2 font-mono">404</h1>
      <p className="text-lg text-gray-400 mb-2">Page not found</p>
      <p className="text-sm text-gray-500 mb-8 max-w-sm text-center">
        The page you're looking for doesn't exist or has been moved.
      </p>

      <div className="flex flex-wrap gap-3 justify-center mb-8">
        {QUICK_LINKS.map((link) => (
          <Link
            key={link.to}
            to={link.to}
            className="inline-flex items-center gap-2 px-4 py-2.5 bg-gray-800 border border-gray-700 text-gray-300 rounded-lg hover:bg-gray-700 hover:text-gray-100 text-sm font-medium transition-all active:scale-[0.98]"
          >
            <span>{link.icon}</span>
            {link.label}
          </Link>
        ))}
      </div>
    </div>
  );
}
