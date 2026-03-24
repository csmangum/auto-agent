import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import EmptyState from './EmptyState';

describe('EmptyState', () => {
  it('renders title', () => {
    render(
      <MemoryRouter>
        <EmptyState title="Nothing here" />
      </MemoryRouter>
    );
    expect(screen.getByText('Nothing here')).toBeInTheDocument();
  });

  it('renders icon when provided', () => {
    render(
      <MemoryRouter>
        <EmptyState title="Empty" icon="📋" />
      </MemoryRouter>
    );
    expect(screen.getByText('📋')).toBeInTheDocument();
  });

  it('renders description when provided', () => {
    render(
      <MemoryRouter>
        <EmptyState title="Empty" description="No items to display" />
      </MemoryRouter>
    );
    expect(screen.getByText('No items to display')).toBeInTheDocument();
  });

  it('renders action link when actionLabel and actionTo are provided', () => {
    render(
      <MemoryRouter>
        <EmptyState title="No claims" actionLabel="Create Claim" actionTo="/claims/new" />
      </MemoryRouter>
    );
    const link = screen.getByRole('link', { name: 'Create Claim' });
    expect(link).toHaveAttribute('href', '/claims/new');
  });

  it('does not render action link when only actionLabel is provided', () => {
    render(
      <MemoryRouter>
        <EmptyState title="No data" actionLabel="Retry" />
      </MemoryRouter>
    );
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('renders children', () => {
    render(
      <MemoryRouter>
        <EmptyState title="Empty">
          <button>Custom action</button>
        </EmptyState>
      </MemoryRouter>
    );
    expect(screen.getByRole('button', { name: 'Custom action' })).toBeInTheDocument();
  });
});
