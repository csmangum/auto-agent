import { matchPath, useLocation, useParams } from 'react-router-dom';
import { useMemo } from 'react';

export interface BreadcrumbItem {
  label: string;
  to?: string;
}

const ROUTE_SEGMENTS: Array<{
  pattern: string;
  label: string;
  paramKey?: 'claimId' | 'name' | 'slug';
}> = [
  { pattern: '/dashboard', label: 'Dashboard' },
  { pattern: '/claims', label: 'Claims' },
  { pattern: '/claims/new', label: 'New Claim' },
  { pattern: '/claims/:claimId', label: 'Claim', paramKey: 'claimId' },
  { pattern: '/workbench', label: 'Workbench' },
  { pattern: '/workbench/queue', label: 'Assignment Queue' },
  { pattern: '/workbench/diary', label: 'Diary / Calendar' },
  { pattern: '/simulate', label: 'Role Simulation' },
  { pattern: '/docs', label: 'Documentation' },
  { pattern: '/docs/:slug', label: 'Doc', paramKey: 'slug' },
  { pattern: '/skills', label: 'Skills' },
  { pattern: '/skills/:name', label: 'Skill', paramKey: 'name' },
  { pattern: '/agents', label: 'Agents & Crews' },
  { pattern: '/cost', label: 'LLM Cost' },
  { pattern: '/system', label: 'System Config' },
  { pattern: '/system/templates', label: 'Note Templates' },
];

function pathDepth(p: string): number {
  return p.split('/').filter(Boolean).length;
}

/** Build hierarchical crumbs from pathname prefixes (e.g. Claims > Claim detail). */
export function useBreadcrumbs(claimBreadcrumbLabel?: string | null): BreadcrumbItem[] {
  const { pathname } = useLocation();
  const params = useParams();

  return useMemo(() => {
    const segments = pathname.split('/').filter(Boolean);
    if (segments.length === 0) return [];

    const items: BreadcrumbItem[] = [];
    for (let i = 1; i <= segments.length; i++) {
      const subPath = `/${segments.slice(0, i).join('/')}`;
      const matches = ROUTE_SEGMENTS.filter((r) =>
        matchPath({ path: r.pattern, end: true }, subPath)
      );
      if (matches.length === 0) continue;
      matches.sort((a, b) => pathDepth(b.pattern) - pathDepth(a.pattern));
      const segDef = matches[0];
      const isLast = i === segments.length;
      const to = isLast ? undefined : subPath;

      let label = segDef.label;
      if (segDef.paramKey && params[segDef.paramKey]) {
        const v = params[segDef.paramKey] as string;
        if (segDef.paramKey === 'claimId') {
          const t = claimBreadcrumbLabel?.trim();
          if (t) {
            label = t.length > 48 ? `${t.slice(0, 48)}…` : t;
          } else {
            label = v.length > 12 ? `${v.slice(0, 8)}…` : v;
          }
        } else if (segDef.paramKey === 'name' || segDef.paramKey === 'slug') {
          label = decodeURIComponent(v).replace(/_/g, ' ');
        }
      }

      items.push({ label, to });
    }

    return items;
  }, [pathname, params, claimBreadcrumbLabel]);
}
