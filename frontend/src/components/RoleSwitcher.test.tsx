import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { RoleSimulationProvider } from '../context/RoleSimulationContext';
import RoleSwitcher from './RoleSwitcher';

function renderRoleSwitcher(initialPath = '/') {
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

  it('shows role descriptions in dropdown', () => {
    renderRoleSwitcher();
    fireEvent.click(screen.getByRole('button', { name: /Adjuster/i }));
    expect(screen.getByText('Internal claims adjuster with full system access')).toBeInTheDocument();
    expect(screen.getByText('Policyholder or claimant filing and tracking claims')).toBeInTheDocument();
    expect(screen.getByText('Body shop managing vehicle repairs and supplements')).toBeInTheDocument();
    expect(screen.getByText('Other insurance company or third-party claimant')).toBeInTheDocument();
  });

  it('navigates to /simulate when selecting a non-adjuster role', () => {
    renderRoleSwitcher();
    fireEvent.click(screen.getByRole('button', { name: /Adjuster/i }));
    fireEvent.click(screen.getByText('Customer'));
    expect(screen.getByText('Customer')).toBeInTheDocument();
  });

  it('navigates to / when selecting adjuster role', () => {
    localStorage.setItem('simulation_role', 'customer');
    renderRoleSwitcher();
    fireEvent.click(screen.getByRole('button', { name: /Customer/i }));
    fireEvent.click(screen.getByText('Adjuster'));
    expect(screen.getByText('Adjuster')).toBeInTheDocument();
  });

  it('closes dropdown when overlay is clicked and hides options', () => {
    renderRoleSwitcher();
    fireEvent.click(screen.getByRole('button', { name: /Adjuster/i }));
    expect(screen.getByText('Simulate Role')).toBeInTheDocument();
    expect(screen.getByText('Internal claims adjuster with full system access')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('role-switcher-overlay'));
    expect(screen.queryByText('Simulate Role')).not.toBeInTheDocument();
    expect(screen.queryByText('Internal claims adjuster with full system access')).not.toBeInTheDocument();
  });
});
