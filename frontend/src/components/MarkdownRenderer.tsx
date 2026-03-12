import { Suspense, lazy, useState, useCallback, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import type { Components } from 'react-markdown';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

/** Inline code that matches these names is rendered as a link to Claim Types field definitions. */
const CLAIM_DATA_FIELD_NAMES = new Set([
  'claim_data',
  'policy_number',
  'vin',
  'vehicle_year',
  'vehicle_make',
  'vehicle_model',
  'incident_date',
  'incident_description',
  'damage_description',
  'estimated_damage',
  'attachments',
  'claim_type',
]);

const MermaidDiagram = lazy(() => import('./MermaidDiagram'));

function CopyButton({ text, className }: { text: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timeoutRef.current !== null) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  const copy = useCallback(async () => {
    try {
      if (navigator && 'clipboard' in navigator && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        try {
          document.execCommand('copy');
        } finally {
          document.body.removeChild(textarea);
        }
      }
      setCopied(true);
      if (timeoutRef.current !== null) {
        clearTimeout(timeoutRef.current);
      }
      timeoutRef.current = setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      console.error('Failed to copy text to clipboard', error);
    }
  }, [text]);

  const label = copied ? 'Copied!' : 'Copy to clipboard';
  return (
    <button
      type="button"
      onClick={copy}
      aria-label={label}
      title={label}
      className={className ?? 'ml-2 inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-gray-500 hover:bg-gray-700/50 hover:text-gray-300 transition-colors'}
    >
      <span aria-live="polite" className="sr-only">{copied ? 'Copied!' : ''}</span>
      {copied ? (
        <span className="text-emerald-400" aria-hidden="true">Copied!</span>
      ) : (
        <CopyIcon className="size-3.5" />
      )}
    </button>
  );
}

function CopyIcon({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"
      />
    </svg>
  );
}

/** Allowed URL schemes to prevent XSS via javascript:, data:, etc. */
const SAFE_SCHEMES = ['http:', 'https:', 'mailto:'];

/** Segment type for JSON key highlighting */
type JsonSegment = { type: 'key'; value: string } | { type: 'text'; value: string };

function highlightJsonKeys(content: string): React.ReactNode[] {
  const trimmed = content.trim();
  if (!trimmed || (trimmed[0] !== '{' && trimmed[0] !== '[')) return [content];
  const segments: JsonSegment[] = [];
  const keyRe = /"([^"\\]*(?:\\.[^"\\]*)*)"\s*:/g;
  let lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = keyRe.exec(content)) !== null) {
    if (m.index > lastIndex) {
      segments.push({ type: 'text', value: content.slice(lastIndex, m.index) });
    }
    segments.push({ type: 'key', value: m[0] });
    lastIndex = keyRe.lastIndex;
  }
  if (lastIndex < content.length) {
    segments.push({ type: 'text', value: content.slice(lastIndex) });
  }
  if (segments.length === 0) return [content];
  return segments.map((s, i) =>
    s.type === 'key' ? (
      <span key={i} className="text-amber-300">
        {s.value}
      </span>
    ) : (
      <span key={i}>{s.value}</span>
    )
  );
}

/** Generate a URL-safe id from heading text (matches anchors used in docs like crews.md). */
function slugifyHeading(text: string): string {
  return text
    .toLowerCase()
    .replace(/\s*\/\s*/g, '--')
    .replace(/\s+/g, '-')
    .replace(/[^\w-]/g, '');
}

function headingTextFromNode(node: { children?: Array<{ type?: string; value?: string }> } | null): string {
  if (!node?.children) return '';
  return (node.children as Array<{ type?: string; value?: string }>)
    .filter((c) => c.type === 'text' && c.value)
    .map((c) => c.value!)
    .join('');
}

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

/** Languages that get a copy button on fenced code blocks. */
const COPY_BLOCK_LANGS = new Set(['bash', 'sh', 'shell', 'zsh']);

interface MarkdownRendererProps {
  content?: string | null;
}

export default function MarkdownRenderer({ content }: MarkdownRendererProps) {
  // A fresh slug-dedup map is created for each render so that duplicate headings
  // receive unique ids (e.g. "example", "example-1", "example-2") consistently.
  const slugCounts = new Map<string, number>();

  function uniqueSlug(node: Parameters<typeof headingTextFromNode>[0]): string {
    const base = slugifyHeading(headingTextFromNode(node));
    if (!base) return '';
    const count = slugCounts.get(base) ?? 0;
    slugCounts.set(base, count + 1);
    return count === 0 ? base : `${base}-${count}`;
  }

  const components: Components = {
    h1: ({ node, children }) => (
      <h1 id={uniqueSlug(node) || undefined} className="text-3xl font-bold text-white mt-8 mb-4 pb-2 border-b border-sky-500/40 scroll-mt-6">
        {children}
      </h1>
    ),
    h2: ({ node, children }) => (
      <h2 id={uniqueSlug(node) || undefined} className="text-2xl font-semibold text-sky-100 mt-6 mb-3 scroll-mt-6">
        {children}
      </h2>
    ),
    h3: ({ node, children }) => (
      <h3 id={uniqueSlug(node) || undefined} className="text-xl font-semibold text-slate-200 mt-5 mb-2 scroll-mt-6">
        {children}
      </h3>
    ),
    h4: ({ node, children }) => (
      <h4 id={uniqueSlug(node) || undefined} className="text-lg font-medium text-slate-300 mt-4 mb-2 scroll-mt-6">
        {children}
      </h4>
    ),
    p: ({ children }) => (
      <p className="text-slate-400 leading-relaxed mb-4">{children}</p>
    ),
    ul: ({ children }) => (
      <ul className="list-disc pl-6 mb-4 space-y-1 text-slate-400 [&::marker]:text-sky-500/70">
        {children}
      </ul>
    ),
    ol: ({ children }) => (
      <ol className="list-decimal pl-6 mb-4 space-y-1 text-slate-400 [&::marker]:text-sky-500/70">
        {children}
      </ol>
    ),
    li: ({ children }) => <li className="text-slate-400">{children}</li>,
    a: ({ href, children }) => {
      const safeHref = isSafeHref(href) ? (href as string) : '#';
      const isExternal = safeHref.startsWith('http');
      return (
        <a
          href={safeHref}
          className="text-sky-400 hover:text-sky-300 underline underline-offset-2 decoration-sky-500/40 transition-colors"
          target={isExternal ? '_blank' : undefined}
          rel={isExternal ? 'noopener noreferrer' : undefined}
        >
          {children}
        </a>
      );
    },
    table: ({ children }) => (
      <div className="overflow-x-auto mb-4">
        <table className="min-w-full border border-slate-600/60 text-sm">{children}</table>
      </div>
    ),
    thead: ({ children }) => (
      <thead className="bg-slate-800/80 border-b border-sky-500/30">{children}</thead>
    ),
    th: ({ children }) => (
      <th className="border border-slate-600/60 px-4 py-2 text-left font-medium text-slate-200">
        {children}
      </th>
    ),
    td: ({ children }) => (
      <td className="border border-slate-600/60 px-4 py-2 text-slate-400">{children}</td>
    ),
    code: ({ className, children }) => {
      const content = String(children || '');
      const isBlock = className || content.includes('\n');
      const isCommand = content.trim().startsWith('claim-agent');
      if (!isBlock) {
        const trimmed = content.trim();
        const isDataField = CLAIM_DATA_FIELD_NAMES.has(trimmed);
        const codeEl = (
          <code className="bg-slate-800 text-sky-300 px-1.5 py-0.5 rounded text-sm font-mono ring-1 ring-slate-600/50">
            {children}
          </code>
        );
        return (
          <span className="inline-flex items-center">
            {isDataField ? (
              <Link
                to={`/docs/claim-types#${trimmed}`}
                className="text-sky-400 hover:text-sky-300 underline underline-offset-2 decoration-sky-500/40 transition-colors"
              >
                {codeEl}
              </Link>
            ) : (
              codeEl
            )}
            {isCommand && (
              <span className="shrink-0">
                <CopyButton text={trimmed} />
              </span>
            )}
          </span>
        );
      }
      const lang = className?.replace('language-', '') ?? '';
      if (lang === 'mermaid') {
        const code = Array.isArray(children) ? children.join('') : String(children ?? '');
        return (
          <Suspense
            fallback={
              <div className="bg-gray-800/50 border border-gray-700/50 rounded-lg p-8 mb-4 text-center">
                <div className="animate-pulse text-gray-500 text-sm">Loading diagram…</div>
              </div>
            }
          >
            <MermaidDiagram chart={code} />
          </Suspense>
        );
      }
      if (lang === 'tree') {
        const lines = content.split('\n');
        return (
          <pre className="bg-slate-900/80 rounded-lg p-4 overflow-x-auto mb-4 ring-1 ring-slate-600/50 text-sm font-mono">
            <code>
              {lines.map((line, i) => {
                const commentIdx = line.indexOf(' # ');
                const pathPart = commentIdx >= 0 ? line.slice(0, commentIdx) : line;
                const commentPart = commentIdx >= 0 ? line.slice(commentIdx + 3) : null;
                return (
                  <span key={i} className="leading-7 whitespace-pre">
                    <span className="text-sky-200/90">{pathPart}</span>
                    {commentPart != null && (
                      <span className="text-slate-500"> # {commentPart}</span>
                    )}
                    {i < lines.length - 1 && <br />}
                  </span>
                );
              })}
            </code>
          </pre>
        );
      }
      const hasCopyButton = COPY_BLOCK_LANGS.has(lang);
      const isJson = lang === 'json' || /^\s*[{[]/.test(content);
      const codeContent = isJson ? highlightJsonKeys(content) : children;
      return (
        <div className="relative group mb-4">
          {hasCopyButton && (
            <CopyButton
              text={content}
              className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 focus:opacity-100 inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-gray-400 bg-slate-700/80 hover:bg-slate-600/80 hover:text-gray-200 transition-all"
            />
          )}
          <pre className="bg-slate-900/80 text-slate-300 rounded-lg p-4 overflow-x-auto ring-1 ring-slate-600/50">
            <code className="text-sm font-mono">{codeContent}</code>
          </pre>
        </div>
      );
    },
    blockquote: ({ children }) => (
      <blockquote className="border-l-4 border-sky-500/50 pl-4 my-4 text-slate-400 italic">
        {children}
      </blockquote>
    ),
    hr: () => <hr className="my-6 border-slate-600/60" />,
    strong: ({ children }) => (
      <strong className="font-semibold text-slate-200">{children}</strong>
    ),
  };

  if (!content) return null;

  return (
    <div className="max-w-none">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
