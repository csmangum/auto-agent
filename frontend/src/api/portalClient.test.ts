import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  getPortalSession,
  setPortalSession,
  clearPortalSession,
  portalApi,
} from './portalClient';

describe('portalClient session helpers', () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it('getPortalSession returns null when empty', () => {
    expect(getPortalSession()).toBeNull();
  });

  it('setPortalSession and getPortalSession round-trip', () => {
    setPortalSession({ token: 'abc123' });
    expect(getPortalSession()).toEqual({ token: 'abc123' });
  });

  it('setPortalSession with policy and vin', () => {
    setPortalSession({
      policyNumber: 'POL-001',
      vin: '1HGBH41JXMN109186',
    });
    expect(getPortalSession()).toEqual({
      policyNumber: 'POL-001',
      vin: '1HGBH41JXMN109186',
    });
  });

  it('clearPortalSession removes session', () => {
    setPortalSession({ token: 'abc123' });
    expect(getPortalSession()).toEqual({ token: 'abc123' });
    clearPortalSession();
    expect(getPortalSession()).toBeNull();
  });

  it('getPortalSession returns null for invalid JSON', () => {
    const spy = vi.spyOn(Storage.prototype, 'getItem').mockReturnValue('invalid-json');
    try {
      expect(getPortalSession()).toBeNull();
    } finally {
      spy.mockRestore();
    }
  });
});

describe('portalApi', () => {
  let mockFetch: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    sessionStorage.clear();
    setPortalSession({ token: 'tok' });
    mockFetch = vi.fn();
    vi.stubGlobal('fetch', mockFetch);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function mockOk(data: unknown) {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(data),
      text: () => Promise.resolve(JSON.stringify(data)),
    });
  }

  function mockError(status: number, body: string) {
    mockFetch.mockResolvedValue({
      ok: false,
      status,
      text: () => Promise.resolve(body),
    });
  }

  it('getClaims without params', async () => {
    const data = { claims: [{ id: '1' }], total: 1 };
    mockOk(data);
    const result = await portalApi.getClaims();
    expect(result).toEqual(data);
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/portal/claims',
      expect.objectContaining({
        headers: expect.objectContaining({ 'X-Claim-Access-Token': 'tok' }),
      }),
    );
  });

  it('getClaims with limit and offset', async () => {
    mockOk({ claims: [], total: 0 });
    await portalApi.getClaims({ limit: 10, offset: 5 });
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain('limit=10');
    expect(url).toContain('offset=5');
  });

  it('getClaim fetches single claim', async () => {
    const claim = { id: 'CLM-1', status: 'open' };
    mockOk(claim);
    const result = await portalApi.getClaim('CLM-1');
    expect(result).toEqual(claim);
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/portal/claims/CLM-1',
      expect.any(Object),
    );
  });

  it('getClaimHistory', async () => {
    const data = { history: [{ event: 'created' }] };
    mockOk(data);
    const result = await portalApi.getClaimHistory('CLM-2');
    expect(result).toEqual(data);
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/portal/claims/CLM-2/history',
      expect.any(Object),
    );
  });

  it('getDocuments without params', async () => {
    const data = { documents: [], total: 0 };
    mockOk(data);
    const result = await portalApi.getDocuments('CLM-3');
    expect(result).toEqual(data);
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/portal/claims/CLM-3/documents',
      expect.any(Object),
    );
  });

  it('getDocuments with document_type param', async () => {
    mockOk({ documents: [], total: 0 });
    await portalApi.getDocuments('CLM-3', { document_type: 'photo' });
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain('document_type=photo');
  });

  it('uploadDocument sends FormData via POST', async () => {
    const mockResult = { document_id: 1, document: {} };
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockResult),
    });
    const file = new File(['data'], 'photo.jpg', { type: 'image/jpeg' });
    const result = await portalApi.uploadDocument('CLM-4', file, 'photo');
    expect(result).toEqual(mockResult);
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('/api/portal/claims/CLM-4/documents'),
      expect.objectContaining({
        method: 'POST',
        body: expect.any(FormData),
      }),
    );
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain('document_type=photo');
  });

  it('uploadDocument without documentType omits query param', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ document_id: 2, document: {} }),
    });
    const file = new File(['data'], 'scan.png', { type: 'image/png' });
    await portalApi.uploadDocument('CLM-4', file);
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toBe('/api/portal/claims/CLM-4/documents');
  });

  it('getDocumentRequests', async () => {
    const data = { document_requests: [], total: 0 };
    mockOk(data);
    const result = await portalApi.getDocumentRequests('CLM-5');
    expect(result).toEqual(data);
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/portal/claims/CLM-5/document-requests',
      expect.any(Object),
    );
  });

  it('getRepairStatus', async () => {
    const data = { latest: null, history: [], cycle_time_days: null };
    mockOk(data);
    const result = await portalApi.getRepairStatus('CLM-6');
    expect(result).toEqual(data);
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/portal/claims/CLM-6/repair-status',
      expect.any(Object),
    );
  });

  it('getPayments', async () => {
    const data = { payments: [], total: 0 };
    mockOk(data);
    const result = await portalApi.getPayments('CLM-7');
    expect(result).toEqual(data);
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/portal/claims/CLM-7/payments',
      expect.any(Object),
    );
  });

  it('recordFollowUpResponse posts JSON', async () => {
    mockOk({ success: true });
    const result = await portalApi.recordFollowUpResponse('CLM-8', 42, 'My response');
    expect(result).toEqual({ success: true });
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/portal/claims/CLM-8/follow-up/record-response',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ message_id: 42, response_content: 'My response' }),
      }),
    );
  });

  it('fileDispute posts JSON', async () => {
    const body = {
      dispute_type: 'valuation',
      dispute_description: 'Too low',
    };
    mockOk({ resolution: 'pending' });
    const result = await portalApi.fileDispute('CLM-9', body);
    expect(result).toEqual({ resolution: 'pending' });
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/portal/claims/CLM-9/dispute',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify(body),
      }),
    );
  });

  it('throws on non-ok response with JSON detail', async () => {
    mockError(403, JSON.stringify({ detail: 'Forbidden' }));
    await expect(portalApi.getClaims()).rejects.toThrow('Forbidden');
  });

  it('throws with raw text on non-JSON error body', async () => {
    mockError(500, 'Internal Server Error');
    await expect(portalApi.getClaim('x')).rejects.toThrow(
      'API error 500: Internal Server Error',
    );
  });

  it('sends portal headers from session', async () => {
    sessionStorage.clear();
    setPortalSession({ policyNumber: 'POL-1', vin: 'VIN123' });
    mockOk({ claims: [], total: 0 });
    await portalApi.getClaims();
    expect(mockFetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        headers: expect.objectContaining({
          'X-Policy-Number': 'POL-1',
          'X-Vin': 'VIN123',
        }),
      }),
    );
  });
});
