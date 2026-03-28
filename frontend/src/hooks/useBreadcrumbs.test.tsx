import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { useBreadcrumbs } from './useBreadcrumbs';

function CrumbList({ claimLabel }: { claimLabel?: string | null }) {
  const items = useBreadcrumbs(claimLabel);
  return (
    <ol>
      {items.map((c, i) => (
        <li key={i} data-testid={`crumb-${i}`}>
          <span data-testid={`label-${i}`}>{c.label}</span>
          {c.to != null ? <span data-testid={`to-${i}`}>{c.to}</span> : null}
        </li>
      ))}
    </ol>
  );
}

function renderClaimsDetail(path: string, claimLabel?: string | null) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/claims/:claimId" element={<CrumbList claimLabel={claimLabel} />} />
      </Routes>
    </MemoryRouter>
  );
}

function renderSkillDetail(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/skills/:name" element={<CrumbList />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('useBreadcrumbs', () => {
  it('builds hierarchy for claim detail with links on parents', () => {
    renderClaimsDetail('/claims/CLM-001');
    expect(screen.getByTestId('label-0')).toHaveTextContent('Claims');
    expect(screen.getByTestId('to-0')).toHaveTextContent('/claims');
    expect(screen.getByTestId('label-1')).toHaveTextContent('CLM-001');
    expect(screen.queryByTestId('to-1')).toBeNull();
  });

  it('uses claim breadcrumb label when provided and truncates past 48 chars', () => {
    const long =
      'This is a very long claim title that definitely exceeds forty eight characters in length';
    renderClaimsDetail('/claims/CLM-99', long);
    const label = screen.getByTestId('label-1').textContent ?? '';
    expect(label.endsWith('…')).toBe(true);
    expect(label.length).toBeLessThanOrEqual(49);
    expect(long.slice(0, 48)).toBe(label.slice(0, 48));
  });

  it('truncates long claim id when no custom label', () => {
    const id = 'very-long-claim-id-12345';
    renderClaimsDetail(`/claims/${id}`);
    expect(screen.getByTestId('label-1').textContent).toMatch(/^very-lon/);
    expect(screen.getByTestId('label-1').textContent).toContain('…');
  });

  it('decodes skill name and replaces underscores in label', () => {
    renderSkillDetail('/skills/foo_bar_baz');
    expect(screen.getByTestId('label-0')).toHaveTextContent('Skills');
    expect(screen.getByTestId('label-1')).toHaveTextContent('foo bar baz');
  });
});
