/**
 * Accessibility (a11y) audit tests using axe-core via jest-axe.
 *
 * These tests render key UI components and assert that axe finds no
 * accessibility violations. Color-contrast rules are disabled because
 * jsdom does not compute CSS custom properties / Tailwind styles.
 */
import { render } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { configureAxe } from 'jest-axe';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { ThemeProvider } from '../context/ThemeContext';
import { AuthProvider } from '../context/AuthContext';
import { RoleSimulationProvider } from '../context/RoleSimulationContext';

import StatusBadge from './StatusBadge';
import TypeBadge from './TypeBadge';
import EmptyState from './EmptyState';
import StatCard from './StatCard';
import QuickStat from './QuickStat';
import FileDropZone from './FileDropZone';
import PageHeader from './PageHeader';
import Breadcrumbs from './Breadcrumbs';
import ThemeToggle from './ThemeToggle';
import Layout from './Layout';

// colour-contrast is disabled because jsdom does not render CSS / Tailwind
const axe = configureAxe({
  rules: {
    'color-contrast': { enabled: false },
  },
});

// ── helpers ──────────────────────────────────────────────────────────────────

function withRouter(ui: React.ReactElement, initialPath = '/') {
  return (
    <MemoryRouter initialEntries={[initialPath]}>
      {ui}
    </MemoryRouter>
  );
}

function withAllProviders(ui: React.ReactElement, initialPath = '/') {
  return (
    <ThemeProvider>
      <AuthProvider>
        <RoleSimulationProvider>
          <MemoryRouter initialEntries={[initialPath]}>
            {ui}
          </MemoryRouter>
        </RoleSimulationProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}

// ── StatusBadge ───────────────────────────────────────────────────────────────

describe('a11y: StatusBadge', () => {
  it('has no violations for known status', async () => {
    const { container } = render(<StatusBadge status="open" />);
    expect(await axe(container)).toHaveNoViolations();
  });

  it('has no violations for unknown status', async () => {
    const { container } = render(<StatusBadge />);
    expect(await axe(container)).toHaveNoViolations();
  });

  it('has no violations for fraud_suspected status', async () => {
    const { container } = render(<StatusBadge status="fraud_suspected" />);
    expect(await axe(container)).toHaveNoViolations();
  });
});

// ── TypeBadge ─────────────────────────────────────────────────────────────────

describe('a11y: TypeBadge', () => {
  it('has no violations for known type', async () => {
    const { container } = render(<TypeBadge type="new" />);
    expect(await axe(container)).toHaveNoViolations();
  });

  it('has no violations when type is undefined', async () => {
    const { container } = render(<TypeBadge />);
    expect(await axe(container)).toHaveNoViolations();
  });
});

// ── EmptyState ────────────────────────────────────────────────────────────────

describe('a11y: EmptyState', () => {
  it('has no violations with just a title', async () => {
    const { container } = render(
      withRouter(<EmptyState title="No claims found" />)
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it('has no violations with icon, description, and action link', async () => {
    const { container } = render(
      withRouter(
        <EmptyState
          icon="📋"
          title="No claims found"
          description="There are no claims to display."
          actionLabel="Create Claim"
          actionTo="/claims/new"
        />
      )
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});

// ── StatCard ──────────────────────────────────────────────────────────────────

describe('a11y: StatCard', () => {
  it('has no violations with title and value', async () => {
    const { container } = render(<StatCard title="Total Claims" value={42} />);
    expect(await axe(container)).toHaveNoViolations();
  });

  it('has no violations with icon and subtitle', async () => {
    const { container } = render(
      <StatCard title="Open" value={10} subtitle="Pending review" icon="📂" color="green" />
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});

// ── QuickStat ─────────────────────────────────────────────────────────────────

describe('a11y: QuickStat', () => {
  it('has no violations', async () => {
    const { container } = render(<QuickStat label="Pending" value={7} accent="yellow" />);
    expect(await axe(container)).toHaveNoViolations();
  });
});

// ── FileDropZone ──────────────────────────────────────────────────────────────

describe('a11y: FileDropZone', () => {
  it('has no violations with label text child', async () => {
    const { container } = render(
      <FileDropZone onFilesSelected={vi.fn()}>
        <span>Click or drag files here</span>
      </FileDropZone>
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});

// ── PageHeader ────────────────────────────────────────────────────────────────

describe('a11y: PageHeader', () => {
  it('has no violations with title only', async () => {
    const { container } = render(
      withRouter(<PageHeader title="Claim Detail" />)
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it('has no violations with back link and actions', async () => {
    const { container } = render(
      withRouter(
        <PageHeader
          title="Claim Detail"
          subtitle="CLM-2024-001"
          backTo="/claims"
          backLabel="Back to claims"
          actions={<button type="button">Export</button>}
        />
      )
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});

// ── Breadcrumbs ───────────────────────────────────────────────────────────────

describe('a11y: Breadcrumbs', () => {
  const items = [
    { label: 'Claims', to: '/claims' },
    { label: 'CLM-001' },
  ];

  it('has no violations', async () => {
    const { container } = render(
      withRouter(<Breadcrumbs items={items} />)
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it('renders nothing (and has no violations) for a single item', async () => {
    const { container } = render(
      withRouter(<Breadcrumbs items={[{ label: 'Dashboard' }]} />)
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});

// ── ThemeToggle ───────────────────────────────────────────────────────────────

describe('a11y: ThemeToggle', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove('dark');
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: false,
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    });
  });

  it('has no violations', async () => {
    const { container } = render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});

// ── Layout ────────────────────────────────────────────────────────────────────

describe('a11y: Layout', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove('dark');
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: false,
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    });
  });

  it('has no violations on the dashboard route', async () => {
    const { container } = render(
      withAllProviders(
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<div><h2>Dashboard</h2></div>} />
          </Route>
        </Routes>,
        '/'
      )
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});
