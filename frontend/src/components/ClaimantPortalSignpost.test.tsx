import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import ClaimantPortalSignpost from './ClaimantPortalSignpost';

describe('ClaimantPortalSignpost', () => {
  it('renders signpost with link to portal login', () => {
    render(
      <MemoryRouter>
        <ClaimantPortalSignpost />
      </MemoryRouter>
    );
    expect(screen.getByText('Using a claim access token?')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: /Sign in to the Claimant Portal/ });
    expect(link).toHaveAttribute('href', '/portal/login');
  });

  it('has a note role', () => {
    render(
      <MemoryRouter>
        <ClaimantPortalSignpost />
      </MemoryRouter>
    );
    expect(screen.getByRole('note')).toBeInTheDocument();
  });
});
