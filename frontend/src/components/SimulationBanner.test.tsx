import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, beforeEach } from 'vitest';
import { RoleSimulationProvider } from '../context/RoleSimulationContext';
import SimulationBanner from './SimulationBanner';

function renderBanner() {
  return render(
    <RoleSimulationProvider>
      <SimulationBanner />
    </RoleSimulationProvider>
  );
}

describe('SimulationBanner', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('returns null when not simulating (adjuster role)', () => {
    localStorage.setItem('simulation_role', 'adjuster');
    const { container } = renderBanner();
    expect(container.firstChild).toBeNull();
  });

  it('shows banner when simulating customer role', () => {
    localStorage.setItem('simulation_role', 'customer');
    renderBanner();
    expect(screen.getByText(/Simulating:/)).toBeInTheDocument();
    expect(screen.getByText('Customer')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Exit' })).toBeInTheDocument();
  });

  it('shows banner when simulating repair_shop role', () => {
    localStorage.setItem('simulation_role', 'repair_shop');
    renderBanner();
    expect(screen.getByText('Repair Shop')).toBeInTheDocument();
  });

  it('Exit button calls exitSimulation and clears simulation', () => {
    localStorage.setItem('simulation_role', 'customer');
    renderBanner();
    expect(screen.getByText(/Simulating:/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Exit' }));
    expect(localStorage.getItem('simulation_role')).toBe('adjuster');
  });
});
