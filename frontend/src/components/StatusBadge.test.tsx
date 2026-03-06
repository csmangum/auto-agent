import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import StatusBadge from './StatusBadge';

describe('StatusBadge', () => {
  it('renders status with underscores replaced by spaces', () => {
    render(<StatusBadge status="fraud_suspected" />);
    expect(screen.getByText('fraud suspected')).toBeInTheDocument();
  });

  it('renders unknown when status is undefined', () => {
    render(<StatusBadge />);
    expect(screen.getByText('unknown')).toBeInTheDocument();
  });

  it('renders open status', () => {
    render(<StatusBadge status="open" />);
    expect(screen.getByText('open')).toBeInTheDocument();
  });
});
