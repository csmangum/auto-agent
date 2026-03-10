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
    <div className="flex gap-6 min-h-[calc(100vh-120px)]">
      <div className="w-56 shrink-0 hidden md:block">
        <div className="sticky top-6">
          <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
            Documentation
          </h2>
          <nav className="space-y-0.5">
            {pages.map((page) => (
              <NavLink
                key={page.slug}
                to={`/docs/${page.slug}`}
                className={({ isActive }) =>
                  `block px-3 py-1.5 rounded-md text-sm transition-colors ${
                    isActive
                      ? 'bg-blue-50 text-blue-700 font-medium'
                      : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                  }`
                }
              >
                {page.title}
              </NavLink>
            ))}
          </nav>
        </div>
      </div>

      <div className="md:hidden mb-4 w-full">
        <select
          value={slug ?? ''}
          onChange={(e) => navigate(`/docs/${e.target.value}`)}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white"
        >
          {pages.map((page) => (
            <option key={page.slug} value={page.slug}>
              {page.title}
            </option>
          ))}
        </select>
      </div>

      <div className="flex-1 min-w-0">
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-4">
            <p className="text-red-800 text-sm">{error instanceof Error ? error.message : 'Unknown error'}</p>
          </div>
        )}

        {loading ? (
          <div className="animate-pulse space-y-4">
            <div className="h-10 bg-gray-200 rounded w-64" />
            <div className="h-4 bg-gray-100 rounded w-full" />
            <div className="h-4 bg-gray-100 rounded w-5/6" />
            <div className="h-4 bg-gray-100 rounded w-4/6" />
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-gray-200 p-8">
            <MarkdownRenderer content={content} />
          </div>
        )}
      </div>
    </div>
  );
}
