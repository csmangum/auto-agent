import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { BrowserRouter } from 'react-router-dom';
import PageHeader from './PageHeader';

describe('PageHeader', () => {
  it('renders title', () => {
    render(
      <BrowserRouter>
        <PageHeader title="Test Page" />
      </BrowserRouter>
    );
    expect(screen.getByRole('heading', { name: 'Test Page' })).toBeInTheDocument();
  });

  it('renders subtitle when provided', () => {
    render(
      <BrowserRouter>
        <PageHeader title="Test" subtitle="A subtitle" />
      </BrowserRouter>
    );
    expect(screen.getByText('A subtitle')).toBeInTheDocument();
  });

  it('renders back link when backTo provided', () => {
    render(
      <BrowserRouter>
        <PageHeader title="Detail" backTo="/list" />
      </BrowserRouter>
    );
    const link = screen.getByRole('link', { name: /back/i });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute('href', '/list');
  });

  it('uses custom backLabel when provided', () => {
    render(
      <BrowserRouter>
        <PageHeader title="Detail" backTo="/list" backLabel="Back to list" />
      </BrowserRouter>
    );
    expect(screen.getByRole('link', { name: 'Back to list' })).toBeInTheDocument();
  });

  it('renders actions when provided', () => {
    render(
      <BrowserRouter>
        <PageHeader title="Page" actions={<button>Action</button>} />
      </BrowserRouter>
    );
    expect(screen.getByRole('button', { name: 'Action' })).toBeInTheDocument();
  });
});
