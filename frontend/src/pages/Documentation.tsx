import { useEffect } from 'react';
import { useParams, NavLink, useNavigate } from 'react-router-dom';
import MarkdownRenderer from '../components/MarkdownRenderer';
import { useDocs, useDoc } from '../api/queries';

export default function Documentation() {
  const { slug } = useParams<{ slug?: string }>();
  const navigate = useNavigate();
  const { data: docsData, isLoading: docsLoading, error: docsError } = useDocs();
  const { data: docData, isLoading: docLoading, error: docError } = useDoc(slug ?? undefined);
  const pages = docsData?.pages.filter((p) => p.available) ?? [];
  const content = docData?.content ?? null;
  const loading = docsLoading || docLoading;
  const error = docsError ?? docError;

  const firstSlug = pages[0]?.slug;
  useEffect(() => {
    if (!slug && firstSlug) {
      navigate(`/docs/${firstSlug}`, { replace: true });
    }
  }, [slug, firstSlug, navigate]);

  return (
    <div className="flex gap-6 min-h-[calc(100vh-120px)] animate-fade-in">
      {/* Desktop sidebar */}
      <div className="w-56 shrink-0 hidden md:block">
        <div className="sticky top-6">
          <h2 className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider mb-3 px-3">
            Documentation
          </h2>
          <nav className="space-y-0.5">
            {pages.map((page) => (
              <NavLink
                key={page.slug}
                to={`/docs/${page.slug}`}
                className={({ isActive }) =>
                  `block px-3 py-1.5 rounded-lg text-sm transition-colors ${
                    isActive
                      ? 'bg-blue-600/15 text-blue-400 font-medium'
                      : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
                  }`
                }
              >
                {page.title}
              </NavLink>
            ))}
          </nav>
        </div>
      </div>

      {/* Mobile doc selector */}
      <div className="md:hidden mb-4 w-full">
        <select
          value={slug ?? ''}
          onChange={(e) => navigate(`/docs/${e.target.value}`)}
          className="w-full border border-gray-700 rounded-lg px-3 py-2 text-sm bg-gray-800 text-gray-300 focus:outline-none focus:ring-2 focus:ring-blue-500/40"
        >
          {pages.map((page) => (
            <option key={page.slug} value={page.slug}>
              {page.title}
            </option>
          ))}
        </select>
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        {error && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 mb-4 flex items-start gap-3">
            <span className="text-lg">⚠️</span>
            <p className="text-sm text-red-400">{error instanceof Error ? error.message : 'Unknown error'}</p>
          </div>
        )}

        {loading ? (
          <div className="space-y-4">
            <div className="h-10 bg-gray-700/50 rounded w-64 skeleton-shimmer" />
            <div className="h-4 bg-gray-700/30 rounded w-full skeleton-shimmer" />
            <div className="h-4 bg-gray-700/30 rounded w-5/6 skeleton-shimmer" />
            <div className="h-4 bg-gray-700/30 rounded w-4/6 skeleton-shimmer" />
          </div>
        ) : (
          <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-8">
            <MarkdownRenderer content={content} />
          </div>
        )}
      </div>
    </div>
  );
}
