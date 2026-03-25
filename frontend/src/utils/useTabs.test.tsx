import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { MemoryRouter, Routes, Route, useSearchParams } from 'react-router-dom';
import { useTabs } from './useTabs';

const TABS = ['alpha', 'beta'] as const;

function TabsHarness() {
  const [tab, setTab] = useTabs(TABS, 'alpha');
  return (
    <div>
      <span data-testid="active">{tab}</span>
      <button type="button" onClick={() => setTab('beta')}>
        Go beta
      </button>
    </div>
  );
}

function SearchEcho() {
  const [sp] = useSearchParams();
  return <span data-testid="search">{sp.toString()}</span>;
}

describe('useTabs', () => {
  it('uses default tab when tab param is absent', () => {
    render(
      <MemoryRouter initialEntries={['/page']}>
        <Routes>
          <Route
            path="/page"
            element={
              <>
                <TabsHarness />
                <SearchEcho />
              </>
            }
          />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByTestId('active')).toHaveTextContent('alpha');
  });

  it('reads valid tab from URL', () => {
    render(
      <MemoryRouter initialEntries={['/page?tab=beta']}>
        <Routes>
          <Route
            path="/page"
            element={
              <>
                <TabsHarness />
                <SearchEcho />
              </>
            }
          />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByTestId('active')).toHaveTextContent('beta');
  });

  it('removes invalid tab from URL and shows default', async () => {
    render(
      <MemoryRouter initialEntries={['/page?tab=bad&keep=1']}>
        <Routes>
          <Route
            path="/page"
            element={
              <>
                <TabsHarness />
                <SearchEcho />
              </>
            }
          />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByTestId('active')).toHaveTextContent('alpha');
    await waitFor(() => {
      const q = screen.getByTestId('search').textContent ?? '';
      expect(q).not.toContain('tab=');
      expect(q).toContain('keep=1');
    });
  });

  it('setTab updates URL', async () => {
    render(
      <MemoryRouter initialEntries={['/page']}>
        <Routes>
          <Route
            path="/page"
            element={
              <>
                <TabsHarness />
                <SearchEcho />
              </>
            }
          />
        </Routes>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole('button', { name: /go beta/i }));
    await waitFor(() => {
      expect(screen.getByTestId('search').textContent).toContain('tab=beta');
    });
    expect(screen.getByTestId('active')).toHaveTextContent('beta');
  });
});
