import { useState, useEffect } from 'react';
import { useParams, NavLink, useNavigate } from 'react-router-dom';
import MarkdownRenderer from '../components/MarkdownRenderer';
import { getDocs, getDoc } from '../api/client';

export default function Documentation() {
  const { slug } = useParams();
  const navigate = useNavigate();
  const [pages, setPages] = useState([]);
  const [content, setContent] = useState(null);
  const [title, setTitle] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Load page list
  useEffect(() => {
    getDocs()
      .then((data) => {
        const availablePages = data.pages.filter((p) => p.available);
        setPages(availablePages);
        // If no slug specified, navigate to first available page
        if (!slug && availablePages.length > 0) {
          navigate(`/docs/${availablePages[0].slug}`, { replace: true });
        }
      })
      .catch((err) => setError(err.message));
  }, []);

  // Load page content
  useEffect(() => {
    if (!slug) return;
    setLoading(true);
    setError(null);
    getDoc(slug)
      .then((data) => {
        setContent(data.content);
        setTitle(data.title);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [slug]);

  return (
    <div className="flex gap-6 min-h-[calc(100vh-120px)]">
      {/* Sidebar */}
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

      {/* Mobile page selector */}
      <div className="md:hidden mb-4 w-full">
        <select
          value={slug || ''}
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

      {/* Content */}
      <div className="flex-1 min-w-0">
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-4">
            <p className="text-red-800 text-sm">{error}</p>
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
