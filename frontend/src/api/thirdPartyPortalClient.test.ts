import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  getThirdPartyPortalSession,
  setThirdPartyPortalSession,
  clearThirdPartyPortalSession,
  thirdPartyPortalApi,
} from './thirdPartyPortalClient';

const mockFetch = vi.fn();

describe('thirdPartyPortalClient', () => {
  beforeEach(() => {
    mockFetch.mockReset();
    vi.stubGlobal('fetch', mockFetch);
    clearThirdPartyPortalSession();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    clearThirdPartyPortalSession();
  });

  describe('session management', () => {
    it('returns null when no session stored', () => {
      expect(getThirdPartyPortalSession()).toBeNull();
    });

    it('stores and retrieves a session', () => {
      setThirdPartyPortalSession({ claimId: 'CLM-2', token: 'tp-tok' });
      expect(getThirdPartyPortalSession()).toEqual({ claimId: 'CLM-2', token: 'tp-tok' });
    });

    it('clears a session', () => {
      setThirdPartyPortalSession({ claimId: 'CLM-2', token: 'tp-tok' });
      clearThirdPartyPortalSession();
      expect(getThirdPartyPortalSession()).toBeNull();
    });

    it('returns null on corrupt data', () => {
      sessionStorage.setItem('third_party_portal_session', 'not json');
      expect(getThirdPartyPortalSession()).toBeNull();
    });
  });

  describe('API methods', () => {
    beforeEach(() => {
      setThirdPartyPortalSession({ claimId: 'CLM-2', token: 'tp-token' });
    });

    it('getClaim sends correct URL and header', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ id: 'CLM-2', status: 'open' }),
      } as Response);

      const result = await thirdPartyPortalApi.getClaim('CLM-2');
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/third-party-portal/claims/CLM-2',
        expect.objectContaining({
          headers: expect.objectContaining({
            'X-Third-Party-Access-Token': 'tp-token',
          }),
        })
      );
      expect(result).toEqual({ id: 'CLM-2', status: 'open' });
    });

    it('getClaimHistory fetches history', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ claim_id: 'CLM-2', history: [{ id: 1 }], history_total: 1 }),
      } as Response);

      const result = await thirdPartyPortalApi.getClaimHistory('CLM-2');
      expect(result.history_total).toBe(1);
    });

    it('recordFollowUpResponse sends POST', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true }),
      } as Response);

      await thirdPartyPortalApi.recordFollowUpResponse('CLM-2', 10, 'reply');
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/third-party-portal/claims/CLM-2/follow-up/record-response',
        expect.objectContaining({ method: 'POST' })
      );
    });

    it('fileDispute sends POST with dispute payload', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ resolution_type: 'pending', summary: 'filed' }),
      } as Response);

      const result = await thirdPartyPortalApi.fileDispute('CLM-2', {
        dispute_type: 'liability_determination',
        dispute_description: 'I was not at fault',
      });
      expect(result.resolution_type).toBe('pending');
    });

    it('uploadDocument sends FormData with file', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ document_id: 5, document: {} }),
      } as Response);

      const file = new File(['data'], 'doc.pdf', { type: 'application/pdf' });
      await thirdPartyPortalApi.uploadDocument('CLM-2', file);

      const [url, init] = mockFetch.mock.calls[0];
      expect(url).toBe('/api/v1/third-party-portal/claims/CLM-2/documents');
      expect(init.method).toBe('POST');
      expect(init.body).toBeInstanceOf(FormData);
    });

    it('uploadDocument appends document_type query param', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ document_id: 6, document: {} }),
      } as Response);

      const file = new File(['data'], 'doc.pdf', { type: 'application/pdf' });
      await thirdPartyPortalApi.uploadDocument('CLM-2', file, 'police_report');

      const [url] = mockFetch.mock.calls[0];
      expect(url).toContain('document_type=police_report');
    });

    it('throws on non-ok response', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 401,
        text: async () => JSON.stringify({ detail: 'Unauthorized' }),
      } as Response);

      await expect(thirdPartyPortalApi.getClaim('CLM-2')).rejects.toThrow('Unauthorized');
    });
  });
});
