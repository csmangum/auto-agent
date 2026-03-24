import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { PortalProvider } from '../context/PortalContext';
import { RepairPortalProvider } from '../context/RepairPortalProvider';
import PortalLogin from './PortalLogin';

const mockGetClaims = vi.fn();
const mockClearPortalSession = vi.fn();
const mockGetRepairClaim = vi.fn();

vi.mock('../api/portalClient', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/portalClient')>();
  return {
    ...actual,
    portalApi: {
      ...actual.portalApi,
      getClaims: (...args: unknown[]) => mockGetClaims(...args),
    },
    clearPortalSession: (...args: unknown[]) => mockClearPortalSession(...args),
  };
});

vi.mock('../api/repairPortalClient', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/repairPortalClient')>();
  return {
    ...actual,
    repairPortalApi: {
      ...actual.repairPortalApi,
      getClaim: (...args: unknown[]) => mockGetRepairClaim(...args),
    },
  };
});

function createWrapper(initialPath = '/portal/login') {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <PortalProvider>
        <RepairPortalProvider>
          <MemoryRouter initialEntries={[initialPath]}>{children}</MemoryRouter>
        </RepairPortalProvider>
      </PortalProvider>
    );
  };
}

describe('PortalLogin', () => {
  const Wrapper = createWrapper();

  beforeEach(() => {
    vi.clearAllMocks();
    mockGetClaims.mockResolvedValue({ claims: [{ id: 'CLM-1' }], total: 1 });
    mockGetRepairClaim.mockResolvedValue({ id: 'CLM-1' });
  });

  it('renders policy/VIN and token mode tabs', () => {
    render(
      <Wrapper>
        <PortalLogin />
      </Wrapper>
    );
    expect(screen.getByText('Claimant Portal')).toBeInTheDocument();
    expect(screen.getByText('Policy & VIN')).toBeInTheDocument();
    expect(screen.getByText('Access Token')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('e.g. POL-12345')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('17-character vehicle ID')).toBeInTheDocument();
  });

  it('switches to token mode and shows token input', () => {
    render(
      <Wrapper>
        <PortalLogin />
      </Wrapper>
    );
    fireEvent.click(screen.getByText('Access Token'));
    expect(screen.getByPlaceholderText(/paste token from email/i)).toBeInTheDocument();
    expect(screen.queryByPlaceholderText('e.g. POL-12345')).not.toBeInTheDocument();
  });

  it('shows validation error when token is empty in token mode', async () => {
    render(
      <Wrapper>
        <PortalLogin />
      </Wrapper>
    );
    fireEvent.click(screen.getByText('Access Token'));
    fireEvent.click(screen.getByRole('button', { name: 'Sign In' }));
    await waitFor(() => {
      expect(screen.getByText('Access token is required')).toBeInTheDocument();
    });
  });

  it('shows validation error when policy and VIN are empty in policy mode', async () => {
    render(
      <Wrapper>
        <PortalLogin />
      </Wrapper>
    );
    fireEvent.click(screen.getByRole('button', { name: 'Sign In' }));
    await waitFor(() => {
      expect(screen.getByText('Policy number and VIN are required')).toBeInTheDocument();
    });
  });

  it('successful login calls getClaims and navigates', async () => {
    render(
      <Wrapper>
        <PortalLogin />
      </Wrapper>
    );
    fireEvent.change(screen.getByPlaceholderText('e.g. POL-12345'), {
      target: { value: 'POL-123' },
    });
    fireEvent.change(screen.getByPlaceholderText('17-character vehicle ID'), {
      target: { value: '1HGBH41JXMN109186' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Sign In' }));

    await waitFor(() => {
      expect(mockGetClaims).toHaveBeenCalledWith({ limit: 1 });
    });
  });

  it('shows error when getClaims returns empty', async () => {
    mockGetClaims.mockResolvedValue({ claims: [], total: 0 });
    render(
      <Wrapper>
        <PortalLogin />
      </Wrapper>
    );
    fireEvent.change(screen.getByPlaceholderText('e.g. POL-12345'), {
      target: { value: 'POL-123' },
    });
    fireEvent.change(screen.getByPlaceholderText('17-character vehicle ID'), {
      target: { value: '1HGBH41JXMN109186' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Sign In' }));

    await waitFor(() => {
      expect(mockClearPortalSession).toHaveBeenCalled();
      expect(screen.getByText('No claims found. Please check your information.')).toBeInTheDocument();
    });
  });

  it('shows error on API failure', async () => {
    mockGetClaims.mockRejectedValue(new Error('Network error'));
    render(
      <Wrapper>
        <PortalLogin />
      </Wrapper>
    );
    fireEvent.change(screen.getByPlaceholderText('e.g. POL-12345'), {
      target: { value: 'POL-123' },
    });
    fireEvent.change(screen.getByPlaceholderText('17-character vehicle ID'), {
      target: { value: '1HGBH41JXMN109186' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Sign In' }));

    await waitFor(() => {
      expect(screen.getByText('Network error')).toBeInTheDocument();
    });
  });

  it('switches to repair-shop mode when claim_id and token in URL', () => {
    const WrapperWithParams = createWrapper('/portal/login?claim_id=CLM-1&token=abc123');
    render(
      <WrapperWithParams>
        <PortalLogin />
      </WrapperWithParams>
    );
    // When both claim_id and token are in the URL, the page switches to repair-shop mode
    expect(screen.getByText('Repair Shop Portal')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('e.g. CLM-...')).toBeInTheDocument();
  });

  it('successful token login calls getClaims', async () => {
    render(
      <Wrapper>
        <PortalLogin />
      </Wrapper>
    );
    fireEvent.click(screen.getByText('Access Token'));
    fireEvent.change(screen.getByPlaceholderText(/paste token from email/i), {
      target: { value: 'my-token-123' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Sign In' }));

    await waitFor(() => {
      expect(mockGetClaims).toHaveBeenCalledWith({ limit: 1 });
    });
  });

  it('shows Verifying when loading', async () => {
    mockGetClaims.mockImplementation(() => new Promise((r) => setTimeout(r, 1000)));
    render(
      <Wrapper>
        <PortalLogin />
      </Wrapper>
    );
    fireEvent.change(screen.getByPlaceholderText('e.g. POL-12345'), {
      target: { value: 'POL-123' },
    });
    fireEvent.change(screen.getByPlaceholderText('17-character vehicle ID'), {
      target: { value: '1HGBH41JXMN109186' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Sign In' }));
    expect(screen.getByRole('button', { name: 'Verifying...' })).toBeInTheDocument();
  });

  it('shows repair shop form when Repair Shop role selected', () => {
    render(
      <Wrapper>
        <PortalLogin />
      </Wrapper>
    );
    fireEvent.click(screen.getByText('Repair Shop'));
    expect(screen.getByText('Repair Shop Portal')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('e.g. CLM-...')).toBeInTheDocument();
  });
});
