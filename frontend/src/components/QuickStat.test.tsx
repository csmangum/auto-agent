import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import QuickStat from './QuickStat';

describe('QuickStat', () => {
  it('renders label and value', () => {
    render(<QuickStat label="Total Claims" value={42} accent="emerald" />);
    expect(screen.getByText('Total Claims')).toBeInTheDocument();
    expect(screen.getByText('42')).toBeInTheDocument();
  });

  it('renders zero value', () => {
    render(<QuickStat label="Active" value={0} accent="blue" />);
    expect(screen.getByText('0')).toBeInTheDocument();
  });

  it('applies accent color class', () => {
    const { container } = render(
      <QuickStat label="Test" value={1} accent="purple" />
    );
    const valueEl = container.querySelector('.text-purple-400');
    expect(valueEl).toBeInTheDocument();
    expect(valueEl).toHaveTextContent('1');
  });
});
