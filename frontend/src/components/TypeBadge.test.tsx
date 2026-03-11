import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import TypeBadge from './TypeBadge';

describe('TypeBadge', () => {
  it('renders known type with correct label', () => {
    render(<TypeBadge type="new" />);
    expect(screen.getByText('new')).toBeInTheDocument();
  });

  it('renders type with underscores as spaces', () => {
    render(<TypeBadge type="total_loss" />);
    expect(screen.getByText('total loss')).toBeInTheDocument();
  });

  it('renders unclassified when type is undefined', () => {
    render(<TypeBadge type={undefined} />);
    expect(screen.getByText('unclassified')).toBeInTheDocument();
  });

  it('renders unknown type with default styling', () => {
    render(<TypeBadge type="unknown_type" />);
    expect(screen.getByText('unknown type')).toBeInTheDocument();
  });

  it('renders fraud type', () => {
    render(<TypeBadge type="fraud" />);
    expect(screen.getByText('fraud')).toBeInTheDocument();
  });
});
