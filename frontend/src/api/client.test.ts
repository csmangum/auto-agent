import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  setAuthToken,
  clearAuthToken,
  getClaimsStats,
  getClaims,
  getClaim,
  processClaimAsync,
} from './client';

describe('API client', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
    clearAuthToken();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('sends request to correct base URL', async () => {
    const mockFetch = vi.mocked(fetch);
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ total_claims: 0, by_status: {}, by_type: {} }),
    } as Response);

    await getClaimsStats();

    expect(mockFetch).toHaveBeenCalledWith(
      '/api/claims/stats',
      expect.objectContaining({
        headers: expect.any(Object),
      })
    );
  });

  it('includes Authorization header when token is set', async () => {
    setAuthToken('sk-test-token');
    const mockFetch = vi.mocked(fetch);
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ total_claims: 0, by_status: {}, by_type: {} }),
    } as Response);

    await getClaimsStats();

    expect(mockFetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer sk-test-token',
        }),
      })
    );
  });

  it('does not include Authorization when token is cleared', async () => {
    setAuthToken('sk-token');
    clearAuthToken();
    const mockFetch = vi.mocked(fetch);
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ total_claims: 0, by_status: {}, by_type: {} }),
    } as Response);

    await getClaimsStats();

    const call = mockFetch.mock.calls[0];
    const headers = call[1]?.headers as Record<string, string>;
    expect(headers?.Authorization).toBeUndefined();
  });

  it('throws on 4xx error without retry', async () => {
    const mockFetch = vi.mocked(fetch);
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      text: async () => 'Not found',
    } as Response);

    await expect(getClaimsStats()).rejects.toThrow(/API error 404/);
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('retries once on 5xx error', async () => {
    const mockFetch = vi.mocked(fetch);
    mockFetch
      .mockResolvedValueOnce({
        ok: false,
        status: 503,
        text: async () => 'Service unavailable',
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ total_claims: 0, by_status: {}, by_type: {} }),
      } as Response);

    const result = await getClaimsStats();

    expect(mockFetch).toHaveBeenCalledTimes(2);
    expect(result).toEqual({ total_claims: 0, by_status: {}, by_type: {} });
  });

  it('getClaims builds query string from params', async () => {
    const mockFetch = vi.mocked(fetch);
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ total: 0, claims: [] }),
    } as Response);

    await getClaims({ status: 'open', limit: 10, offset: 5 });

    expect(mockFetch).toHaveBeenCalledWith(
      '/api/claims?status=open&limit=10&offset=5',
      expect.any(Object)
    );
  });

  it('getClaim fetches by id', async () => {
    const mockFetch = vi.mocked(fetch);
    const mockClaim = { id: 'CLM-001', status: 'open' };
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockClaim,
    } as Response);

    const result = await getClaim('CLM-001');

    expect(mockFetch).toHaveBeenCalledWith(
      '/api/claims/CLM-001',
      expect.any(Object)
    );
    expect(result).toEqual(mockClaim);
  });

  it('processClaimAsync sends FormData with claim and files', async () => {
    const mockFetch = vi.mocked(fetch);
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ claim_id: 'CLM-NEW' }),
    } as Response);

    const payload = {
      policy_number: 'POL-1',
      vin: 'VIN123',
      vehicle_year: 2024,
      vehicle_make: 'Honda',
      vehicle_model: 'Accord',
      incident_date: '2025-01-15',
      incident_description: 'Rear-ended',
      damage_description: 'Bumper damage',
    };
    const file = new File(['content'], 'photo.jpg', { type: 'image/jpeg' });

    await processClaimAsync(payload, [file]);

    expect(mockFetch).toHaveBeenCalledWith(
      '/api/claims/process/async',
      expect.objectContaining({
        method: 'POST',
        body: expect.any(FormData),
        credentials: 'include',
        headers: expect.any(Object),
      })
    );
    const formData = (mockFetch.mock.calls[0][1] as { body: FormData }).body;
    expect(formData.get('claim')).toBe(JSON.stringify(payload));
    expect(formData.get('files')).toBe(file);
  });

  it('processClaimAsync includes Authorization header when token is set', async () => {
    setAuthToken('sk-claim-token');
    const mockFetch = vi.mocked(fetch);
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ claim_id: 'CLM-NEW' }),
    } as Response);

    const payload = {
      policy_number: 'POL-1',
      vin: 'VIN123',
      vehicle_year: 2024,
      vehicle_make: 'Honda',
      vehicle_model: 'Accord',
      incident_date: '2025-01-15',
      incident_description: 'Rear-ended',
      damage_description: 'Bumper damage',
    };

    await processClaimAsync(payload);

    expect(mockFetch).toHaveBeenCalledWith(
      '/api/claims/process/async',
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer sk-claim-token',
        }),
      })
    );
  });

  it('processClaimAsync sends multiple files', async () => {
    const mockFetch = vi.mocked(fetch);
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ claim_id: 'CLM-NEW' }),
    } as Response);

    const payload = {
      policy_number: 'POL-1',
      vin: 'VIN123',
      vehicle_year: 2024,
      vehicle_make: 'Honda',
      vehicle_model: 'Accord',
      incident_date: '2025-01-15',
      incident_description: 'Rear-ended',
      damage_description: 'Bumper damage',
    };
    const file1 = new File(['a'], 'photo1.jpg', { type: 'image/jpeg' });
    const file2 = new File(['b'], 'photo2.png', { type: 'image/png' });

    await processClaimAsync(payload, [file1, file2]);

    const formData = (mockFetch.mock.calls[0][1] as { body: FormData }).body;
    const files = formData.getAll('files');
    expect(files).toHaveLength(2);
    expect(files[0]).toBe(file1);
    expect(files[1]).toBe(file2);
  });
});
