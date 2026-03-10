import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, beforeEach } from 'vitest';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { AuthProvider } from '../context/AuthContext';
import Layout from './Layout';

describe('Layout', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  function renderLayout(initialPath = '/') {
    return render(
      <AuthProvider>
        <MemoryRouter initialEntries={[initialPath]}>
          <Routes>
            <Route element={<Layout />}>
              <Route path="/" element={<div>Dashboard content</div>} />
              <Route path="/claims" element={<div>Claims content</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    );
  }

  it('renders brand and navigation', () => {
    renderLayout();
    expect(screen.getAllByText('Claims System').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Observability Dashboard')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /dashboard/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /claims/i })).toBeInTheDocument();
  });

  it('renders outlet content', () => {
    renderLayout();
    expect(screen.getByText('Dashboard content')).toBeInTheDocument();
  });

  it('navigates to claims when link clicked', () => {
    renderLayout();
    fireEvent.click(screen.getByRole('link', { name: /claims/i }));
    expect(screen.getByText('Claims content')).toBeInTheDocument();
  });

  it('opens mobile menu when hamburger clicked', () => {
    renderLayout();
    const menuBtn = screen.getByRole('button', { name: 'Open menu' });
    expect(menuBtn).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(menuBtn);
    expect(menuBtn).toHaveAttribute('aria-expanded', 'true');
  });

  it('closes sidebar when overlay clicked', () => {
    renderLayout();
    fireEvent.click(screen.getByRole('button', { name: 'Open menu' }));
    fireEvent.click(screen.getByTestId('sidebar-overlay'));
    expect(screen.getByRole('button', { name: 'Open menu' })).toHaveAttribute('aria-expanded', 'false');
  });
});
