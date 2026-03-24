import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { ThirdPartyPortalProvider } from '../context/ThirdPartyPortalProvider';
import { clearThirdPartyPortalSession } from '../api/thirdPartyPortalClient';
import ThirdPartyPortalLogin from './ThirdPartyPortalLogin';

const mockFetch = vi.fn();
const mockNavigate = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

function renderLogin() {
  return render(
    <ThirdPartyPortalProvider>
      <MemoryRouter>
        <ThirdPartyPortalLogin />
      </MemoryRouter>
    </ThirdPartyPortalProvider>
  );
}

describe('ThirdPartyPortalLogin', () => {
  beforeEach(() => {
    mockFetch.mockReset();
    mockNavigate.mockReset();
    vi.stubGlobal('fetch', mockFetch);
    clearThirdPartyPortalSession();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders the login form', () => {
    renderLogin();
    expect(screen.getByText('Third-Party Portal')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign In' })).toBeInTheDocument();
  });

  it('shows error when fields are empty', async () => {
    renderLogin();
    fireEvent.click(screen.getByRole('button', { name: 'Sign In' }));

    await waitFor(() => {
      expect(screen.getByText('Claim ID and access token are required')).toBeInTheDocument();
    });
  });

  it('navigates on successful login', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ id: 'CLM-2' }),
    } as Response);

    renderLogin();
    fireEvent.change(screen.getByPlaceholderText('e.g. CLM-...'), {
      target: { value: 'CLM-2' },
    });
    fireEvent.change(screen.getByPlaceholderText('Paste token from the carrier'), {
      target: { value: 'token-123' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Sign In' }));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/third-party-portal/claims/CLM-2', {
        replace: true,
      });
    });
  });

  it('shows error on failed verification', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 403,
      text: async () => JSON.stringify({ detail: 'Forbidden' }),
    } as Response);

    renderLogin();
    fireEvent.change(screen.getByPlaceholderText('e.g. CLM-...'), {
      target: { value: 'CLM-2' },
    });
    fireEvent.change(screen.getByPlaceholderText('Paste token from the carrier'), {
      target: { value: 'bad-token' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Sign In' }));

    await waitFor(() => {
      expect(screen.getByText('Forbidden')).toBeInTheDocument();
    });
  });

  it('toggles token visibility', () => {
    renderLogin();
    const tokenInput = screen.getByPlaceholderText('Paste token from the carrier');
    expect(tokenInput).toHaveAttribute('type', 'password');

    fireEvent.click(screen.getByText('Show'));
    expect(tokenInput).toHaveAttribute('type', 'text');
  });
});
