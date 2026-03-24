import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { RepairPortalProvider } from '../context/RepairPortalProvider';
import { clearRepairPortalSession } from '../api/repairPortalClient';
import RepairPortalLogin from './RepairPortalLogin';

const mockFetch = vi.fn();
const mockNavigate = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

function renderLogin() {
  return render(
    <RepairPortalProvider>
      <MemoryRouter>
        <RepairPortalLogin />
      </MemoryRouter>
    </RepairPortalProvider>
  );
}

describe('RepairPortalLogin', () => {
  beforeEach(() => {
    mockFetch.mockReset();
    mockNavigate.mockReset();
    vi.stubGlobal('fetch', mockFetch);
    clearRepairPortalSession();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders the login form', () => {
    renderLogin();
    expect(screen.getByText('Repair Shop Portal')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('e.g. CLM-...')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Paste token from the carrier')).toBeInTheDocument();
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
      json: async () => ({ id: 'CLM-1' }),
    } as Response);

    renderLogin();
    fireEvent.change(screen.getByPlaceholderText('e.g. CLM-...'), {
      target: { value: 'CLM-1' },
    });
    fireEvent.change(screen.getByPlaceholderText('Paste token from the carrier'), {
      target: { value: 'token-123' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Sign In' }));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/repair-portal/claims/CLM-1', {
        replace: true,
      });
    });
  });

  it('shows error on failed verification', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 401,
      text: async () => JSON.stringify({ detail: 'Invalid token' }),
    } as Response);

    renderLogin();
    fireEvent.change(screen.getByPlaceholderText('e.g. CLM-...'), {
      target: { value: 'CLM-1' },
    });
    fireEvent.change(screen.getByPlaceholderText('Paste token from the carrier'), {
      target: { value: 'bad-token' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Sign In' }));

    await waitFor(() => {
      expect(screen.getByText('Invalid token')).toBeInTheDocument();
    });
  });

  it('toggles token visibility', () => {
    renderLogin();
    const tokenInput = screen.getByPlaceholderText('Paste token from the carrier');
    expect(tokenInput).toHaveAttribute('type', 'password');

    fireEvent.click(screen.getByText('Show'));
    expect(tokenInput).toHaveAttribute('type', 'text');

    fireEvent.click(screen.getByText('Hide'));
    expect(tokenInput).toHaveAttribute('type', 'password');
  });
});
