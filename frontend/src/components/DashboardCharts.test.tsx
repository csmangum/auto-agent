import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import DashboardCharts from './DashboardCharts';

const typeData = [
  { name: 'new', value: 50, fill: '#3B82F6' },
  { name: 'duplicate', value: 20, fill: '#F97316' },
];

const statusData = [
  { name: 'open', value: 30, fill: '#22C55E' },
  { name: 'closed', value: 40, fill: '#6B7280' },
];

describe('DashboardCharts', () => {
  it('renders claims by type section when typeData has items', () => {
    render(<DashboardCharts typeData={typeData} statusData={statusData} />);

    expect(screen.getByText('Claims by Type')).toBeInTheDocument();
    expect(screen.getByText('Claims by Status')).toBeInTheDocument();
    expect(screen.queryByText('No data')).not.toBeInTheDocument();
  });

  it('renders both chart sections when data provided', () => {
    render(<DashboardCharts typeData={typeData} statusData={statusData} />);

    expect(screen.getByText('Claims by Type')).toBeInTheDocument();
    expect(screen.getByText('Claims by Status')).toBeInTheDocument();
    expect(screen.queryAllByText('No data')).toHaveLength(0);
  });

  it('shows No data when typeData is empty', () => {
    render(<DashboardCharts typeData={[]} statusData={statusData} />);

    expect(screen.getByText('Claims by Type')).toBeInTheDocument();
    expect(screen.getByText('No data')).toBeInTheDocument();
  });

  it('shows No data when statusData is empty', () => {
    render(<DashboardCharts typeData={typeData} statusData={[]} />);

    expect(screen.getByText('Claims by Status')).toBeInTheDocument();
    const noDataElements = screen.getAllByText('No data');
    expect(noDataElements.length).toBe(1);
  });

  it('shows No data for both charts when both are empty', () => {
    render(<DashboardCharts typeData={[]} statusData={[]} />);

    const noDataElements = screen.getAllByText('No data');
    expect(noDataElements).toHaveLength(2);
  });
});
