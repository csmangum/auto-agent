import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { RoleSimulationProvider } from '../context/RoleSimulationContext';
import RoleSwitcher from './RoleSwitcher';

function renderRoleSwitcher(initialPath = '/') {
  const mockNavigate = vi.fn();
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <RoleSimulationProvider>
        <RoleSwitcher />
      </RoleSimulationProvider>
    </MemoryRouter>
  );
}

describe('RoleSwitcher', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('renders current role label', () => {
    localStorage.setItem('simulation_role', 'adjuster');
    renderRoleSwitcher();
    expect(screen.getByText('Adjuster')).toBeInTheDocument();
  });

  it('opens dropdown when clicked', () => {
    renderRoleSwitcher();
    fireEvent.click(screen.getByRole('button', { name: /Adjuster/i }));
    expect(screen.getByText('Simulate Role')).toBeInTheDocument();
    expect(screen.getByText('Customer')).toBeInTheDocument();
    expect(screen.getByText('Repair Shop')).toBeInTheDocument();
    expect(screen.getByText('Third Party')).toBeInTheDocument();
  });

  it('closes dropdown when overlay is clicked', () => {
    renderRoleSwitcher();
    fireEvent.click(screen.getByRole('button', { name: /Adjuster/i }));
    expect(screen.getByText('Simulate Role')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('role-switcher-overlay'));
    expect(screen.queryByText('Simulate Role')).not.toBeInTheDocument();
  });

  it('shows Customer when simulating customer', () => {
    localStorage.setItem('simulation_role', 'customer');
    renderRoleSwitcher();
    expect(screen.getByText('Customer')).toBeInTheDocument();
  });
});
