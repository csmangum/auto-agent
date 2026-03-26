import { Link } from 'react-router-dom';
import type { BreadcrumbItem } from '../hooks/useBreadcrumbs';

export default function Breadcrumbs({ items }: { items: BreadcrumbItem[] }) {
  if (items.length <= 1) return null;

  return (
    <nav aria-label="Breadcrumb" className="mb-3 min-w-0">
      <ol className="flex flex-wrap items-center gap-x-1 gap-y-0.5 text-sm text-gray-500 list-none p-0 m-0 max-w-full overflow-x-auto overflow-y-hidden whitespace-nowrap scrollbar-thin">
        {items.map((item, i) => {
          const isLast = i === items.length - 1;
          return (
            <li key={`${item.label}-${i}`} className="flex items-center shrink-0 min-w-0 max-w-[min(100%,14rem)]">
              {i > 0 && (
                <span className="mx-1.5 text-gray-600 shrink-0" aria-hidden>
                  /
                </span>
              )}
              {isLast || !item.to ? (
                <span
                  className="truncate text-gray-400 font-medium"
                  aria-current="page"
                >
                  {item.label}
                </span>
              ) : (
                <Link
                  to={item.to}
                  className="truncate text-gray-500 hover:text-blue-400 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 rounded px-0.5 -mx-0.5"
                >
                  {item.label}
                </Link>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
