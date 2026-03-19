import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import PolicySelect from './PolicySelect';

const mockPolicies = [
  {
    policy_number: 'POL-001',
    status: 'active',
    vehicles: [
      {
        vin: '1HGBH41JXMN109186',
        vehicle_year: 2021,
        vehicle_make: 'Honda',
        vehicle_model: 'Accord',
      },
    ],
    liability_limits: { bi_per_accident: 50000, pd_per_accident: 25000 },
    collision_deductible: 500,
  },
  {
    policy_number: 'POL-002',
    status: 'active',
    vehicles: [],
    liability_limits: { bi_per_accident: 100000, pd_per_accident: 50000 },
    comprehensive_deductible: 250,
  },
];

describe('PolicySelect', () => {
  it('renders placeholder when no selection', () => {
    const onChange = vi.fn();
    render(
      <PolicySelect
        policies={mockPolicies}
        value=""
        onChange={onChange}
      />
    );
    expect(screen.getByText('Select a policy…')).toBeInTheDocument();
  });

  it('renders selected policy', () => {
    const onChange = vi.fn();
    render(
      <PolicySelect
        policies={mockPolicies}
        value="POL-001"
        onChange={onChange}
      />
    );
    expect(screen.getByText('POL-001')).toBeInTheDocument();
  });

  it('opens dropdown on click', () => {
    const onChange = vi.fn();
    render(
      <PolicySelect
        policies={mockPolicies}
        value=""
        onChange={onChange}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /select a policy/i }));
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    expect(screen.getByText('POL-001')).toBeInTheDocument();
    expect(screen.getByText('POL-002')).toBeInTheDocument();
  });

  it('selects policy on row click', () => {
    const onChange = vi.fn();
    render(
      <PolicySelect
        policies={mockPolicies}
        value=""
        onChange={onChange}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /select a policy/i }));
    fireEvent.click(screen.getByText('POL-002'));
    expect(onChange).toHaveBeenCalledWith('POL-002');
  });

  it('keyboard ArrowDown opens and selects next', () => {
    const onChange = vi.fn();
    render(
      <PolicySelect
        policies={mockPolicies}
        value=""
        onChange={onChange}
      />
    );
    const button = screen.getByRole('button', { name: /select a policy/i });
    fireEvent.keyDown(button, { key: 'ArrowDown' });
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    fireEvent.keyDown(button, { key: 'Enter' });
    expect(onChange).toHaveBeenCalledWith('POL-001');
  });

  it('Escape closes dropdown', () => {
    const onChange = vi.fn();
    render(
      <PolicySelect
        policies={mockPolicies}
        value=""
        onChange={onChange}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /select a policy/i }));
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole('button'), { key: 'Escape' });
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('click outside closes dropdown', () => {
    const onChange = vi.fn();
    render(
      <div>
        <PolicySelect
          policies={mockPolicies}
          value=""
          onChange={onChange}
        />
        <div data-testid="outside">Outside</div>
      </div>
    );
    fireEvent.click(screen.getByRole('button', { name: /select a policy/i }));
    expect(screen.getByRole('listbox')).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByTestId('outside'));
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('keyboard ArrowUp selects previous policy', () => {
    const onChange = vi.fn();
    render(
      <PolicySelect
        policies={mockPolicies}
        value="POL-001"
        onChange={onChange}
      />
    );
    const button = screen.getByRole('button', { name: 'POL-001' });
    fireEvent.keyDown(button, { key: 'ArrowDown' });
    fireEvent.keyDown(button, { key: 'ArrowDown' });
    fireEvent.keyDown(button, { key: 'Enter' });
    expect(onChange).toHaveBeenCalledWith('POL-002');
  });
});
