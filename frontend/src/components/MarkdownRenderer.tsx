import { Suspense, lazy } from 'react';
import type { Components } from 'react-markdown';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const MermaidDiagram = lazy(() => import('./MermaidDiagram'));

/** Allowed URL schemes to prevent XSS via javascript:, data:, etc. */
const SAFE_SCHEMES = ['http:', 'https:', 'mailto:'];

function isSafeHref(href: string | null | undefined): boolean {
  if (!href || typeof href !== 'string') return false;
  const trimmed = href.trim();
  if (!trimmed) return false;
  if (trimmed.startsWith('#') || trimmed.startsWith('/')) return true;
  try {
    const url = new URL(trimmed, 'https://example.com');
    return SAFE_SCHEMES.includes(url.protocol);
  } catch {
    return false;
  }
}

const components: Components = {
  h1: ({ children }) => (
    <h1 className="text-3xl font-bold text-gray-900 mt-8 mb-4 pb-2 border-b border-gray-200">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="text-2xl font-semibold text-gray-800 mt-6 mb-3">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="text-xl font-semibold text-gray-700 mt-5 mb-2">{children}</h3>
  ),
  h4: ({ children }) => (
    <h4 className="text-lg font-medium text-gray-700 mt-4 mb-2">{children}</h4>
  ),
  p: ({ children }) => <p className="text-gray-700 leading-relaxed mb-4">{children}</p>,
  ul: ({ children }) => <ul className="list-disc pl-6 mb-4 space-y-1 text-gray-700">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal pl-6 mb-4 space-y-1 text-gray-700">{children}</ol>,
  li: ({ children }) => <li className="text-gray-700">{children}</li>,
  a: ({ href, children }) => {
    const safeHref = isSafeHref(href) ? href : '#';
    return (
      <a
        href={safeHref}
        className="text-blue-600 hover:text-blue-800 underline"
        rel={safeHref.startsWith('http') ? 'noopener noreferrer' : undefined}
      >
        {children}
      </a>
    );
  },
  table: ({ children }) => (
    <div className="overflow-x-auto mb-4">
      <table className="min-w-full border border-gray-200 text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-gray-50">{children}</thead>,
  th: ({ children }) => (
    <th className="border border-gray-200 px-4 py-2 text-left font-medium text-gray-700">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border border-gray-200 px-4 py-2 text-gray-600">{children}</td>
  ),
  code: ({ inline, className, children }) => {
    if (inline) {
      return (
        <code className="bg-gray-100 text-pink-600 px-1.5 py-0.5 rounded text-sm font-mono">
          {children}
        </code>
      );
    }
    const lang = className?.replace('language-', '') ?? '';
    if (lang === 'mermaid') {
      const code = Array.isArray(children) ? children.join('') : String(children ?? '');
      return (
        <Suspense
          fallback={
            <div className="bg-gray-50 border border-gray-200 rounded-lg p-8 mb-4 text-center">
              <div className="animate-pulse text-gray-400 text-sm">Loading diagram...</div>
            </div>
          }
        >
          <MermaidDiagram chart={code} />
        </Suspense>
      );
    }
    return (
      <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 overflow-x-auto mb-4">
        <code className="text-sm font-mono">{children}</code>
      </pre>
    );
  },
  blockquote: ({ children }) => (
    <blockquote className="border-l-4 border-blue-300 pl-4 my-4 text-gray-600 italic">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-6 border-gray-200" />,
  strong: ({ children }) => <strong className="font-semibold text-gray-900">{children}</strong>,
};

interface MarkdownRendererProps {
  content?: string | null;
}

export default function MarkdownRenderer({ content }: MarkdownRendererProps) {
  if (!content) return null;

  return (
    <div className="max-w-none">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
