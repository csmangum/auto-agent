import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, beforeEach } from 'vitest';
import {
  RoleSimulationProvider,
  useRoleSimulation,
  ROLE_DEFINITIONS,
} from './RoleSimulationContext';

function TestConsumer() {
  const { role, roleDef, isSimulating, setRole, exitSimulation } = useRoleSimulation();
  return (
    <div>
      <span data-testid="role">{role}</span>
      <span data-testid="label">{roleDef.label}</span>
      <span data-testid="simulating">{isSimulating ? 'yes' : 'no'}</span>
      <button onClick={() => setRole('customer')}>set-customer</button>
      <button onClick={() => setRole('repair_shop')}>set-repair</button>
      <button onClick={() => exitSimulation()}>exit</button>
    </div>
  );
}

describe('RoleSimulationContext', () => {
  beforeEach(() => {
    localStorage.removeItem('simulation_role');
  });

  it('defaults to adjuster role', () => {
    render(
      <RoleSimulationProvider>
        <TestConsumer />
      </RoleSimulationProvider>
    );
    expect(screen.getByTestId('role').textContent).toBe('adjuster');
    expect(screen.getByTestId('simulating').textContent).toBe('no');
  });

  it('allows switching roles', () => {
    render(
      <RoleSimulationProvider>
        <TestConsumer />
      </RoleSimulationProvider>
    );

    act(() => fireEvent.click(screen.getByText('set-customer')));

    expect(screen.getByTestId('role').textContent).toBe('customer');
    expect(screen.getByTestId('label').textContent).toBe('Customer');
    expect(screen.getByTestId('simulating').textContent).toBe('yes');
    expect(localStorage.getItem('simulation_role')).toBe('customer');
  });

  it('exitSimulation resets to adjuster', () => {
    render(
      <RoleSimulationProvider>
        <TestConsumer />
      </RoleSimulationProvider>
    );

    act(() => fireEvent.click(screen.getByText('set-repair')));
    expect(screen.getByTestId('role').textContent).toBe('repair_shop');

    act(() => fireEvent.click(screen.getByText('exit')));
    expect(screen.getByTestId('role').textContent).toBe('adjuster');
    expect(screen.getByTestId('simulating').textContent).toBe('no');
  });

  it('restores role from localStorage', () => {
    localStorage.setItem('simulation_role', 'third_party');
    render(
      <RoleSimulationProvider>
        <TestConsumer />
      </RoleSimulationProvider>
    );
    expect(screen.getByTestId('role').textContent).toBe('third_party');
  });

  it('ignores invalid localStorage values', () => {
    localStorage.setItem('simulation_role', 'invalid_role');
    render(
      <RoleSimulationProvider>
        <TestConsumer />
      </RoleSimulationProvider>
    );
    expect(screen.getByTestId('role').textContent).toBe('adjuster');
  });

  it('ROLE_DEFINITIONS has all four roles', () => {
    expect(Object.keys(ROLE_DEFINITIONS)).toEqual([
      'adjuster',
      'customer',
      'repair_shop',
      'third_party',
    ]);
  });

  it('throws when useRoleSimulation is used outside provider', () => {
    function Bad() {
      useRoleSimulation();
      return null;
    }
    expect(() => render(<Bad />)).toThrow(
      'useRoleSimulation must be used within RoleSimulationProvider'
    );
  });
});
