import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import NewClaimForm from './NewClaimForm';

vi.mock('../api/client', () => ({
  processClaimAsync: vi.fn(),
  streamClaimUpdates: vi.fn(),
}));

describe('NewClaimForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders form with required fields', () => {
    render(
      <MemoryRouter>
        <NewClaimForm />
      </MemoryRouter>
    );
    expect(screen.getByText('New Claim')).toBeInTheDocument();
    expect(screen.getByLabelText(/policy number/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/vin/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/incident date/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /submit|process/i })).toBeInTheDocument();
  });
});
