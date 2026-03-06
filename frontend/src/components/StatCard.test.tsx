import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import StatCard from './StatCard';

describe('StatCard', () => {
  it('renders title and value', () => {
    render(<StatCard title="Total" value={42} />);
    expect(screen.getByText('Total')).toBeInTheDocument();
    expect(screen.getByText('42')).toBeInTheDocument();
  });

  it('renders subtitle when provided', () => {
    render(<StatCard title="Active" value={10} subtitle="Pending review" />);
    expect(screen.getByText('Pending review')).toBeInTheDocument();
  });

  it('renders icon when provided', () => {
    render(<StatCard title="Claims" value={5} icon="📋" />);
    expect(screen.getByText('📋')).toBeInTheDocument();
  });
});
