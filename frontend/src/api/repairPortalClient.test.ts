import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  getRepairPortalSession,
  setRepairPortalSession,
  clearRepairPortalSession,
  repairPortalApi,
} from './repairPortalClient';

const mockFetch = vi.fn();

describe('repairPortalClient', () => {
  beforeEach(() => {
    mockFetch.mockReset();
    vi.stubGlobal('fetch', mockFetch);
    clearRepairPortalSession();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    clearRepairPortalSession();
  });

  describe('session management', () => {
    it('returns null when no session stored', () => {
      expect(getRepairPortalSession()).toBeNull();
    });

    it('stores and retrieves a session', () => {
      setRepairPortalSession({ claimId: 'CLM-1', token: 'tok' });
      expect(getRepairPortalSession()).toEqual({ claimId: 'CLM-1', token: 'tok' });
    });

    it('clears a session', () => {
      setRepairPortalSession({ claimId: 'CLM-1', token: 'tok' });
      clearRepairPortalSession();
      expect(getRepairPortalSession()).toBeNull();
    });

    it('returns null on corrupt sessionStorage data', () => {
      sessionStorage.setItem('repair_portal_session', '{bad json');
      expect(getRepairPortalSession()).toBeNull();
    });
  });

  describe('API methods', () => {
    beforeEach(() => {
      setRepairPortalSession({ claimId: 'CLM-1', token: 'test-token' });
    });

    it('getClaim sends correct URL and auth header', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ id: 'CLM-1', status: 'open' }),
      } as Response);

      const result = await repairPortalApi.getClaim('CLM-1');

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/repair-portal/claims/CLM-1',
        expect.objectContaining({
          headers: expect.objectContaining({
            'X-Repair-Shop-Access-Token': 'test-token',
          }),
        })
      );
      expect(result).toEqual({ id: 'CLM-1', status: 'open' });
    });

    it('getClaimHistory fetches history', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ claim_id: 'CLM-1', history: [], history_total: 0 }),
      } as Response);

      const result = await repairPortalApi.getClaimHistory('CLM-1');
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/repair-portal/claims/CLM-1/history',
        expect.any(Object)
      );
      expect(result.history_total).toBe(0);
    });

    it('getRepairStatus fetches repair status', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ latest: null, history: [], cycle_time_days: null }),
      } as Response);

      const result = await repairPortalApi.getRepairStatus('CLM-1');
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/repair-portal/claims/CLM-1/repair-status',
        expect.any(Object)
      );
      expect(result.latest).toBeNull();
    });

    it('postRepairStatus sends POST with body', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true, repair_status_id: 1 }),
      } as Response);

      await repairPortalApi.postRepairStatus('CLM-1', { status: 'received' });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/repair-portal/claims/CLM-1/repair-status',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ status: 'received' }),
        })
      );
    });

    it('postSupplemental sends POST with body', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          claim_id: 'CLM-1',
          status: 'processing',
          supplemental_amount: 500,
          summary: 'ok',
        }),
      } as Response);

      const result = await repairPortalApi.postSupplemental('CLM-1', {
        supplemental_damage_description: 'hidden rust',
      });
      expect(result.supplemental_amount).toBe(500);
    });

    it('recordFollowUpResponse sends POST', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ success: true }),
      } as Response);

      const result = await repairPortalApi.recordFollowUpResponse('CLM-1', 42, 'got it');
      expect(result.success).toBe(true);
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/repair-portal/claims/CLM-1/follow-up/record-response',
        expect.objectContaining({ method: 'POST' })
      );
    });

    it('throws on non-ok response', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 403,
        text: async () => JSON.stringify({ detail: 'Forbidden' }),
      } as Response);

      await expect(repairPortalApi.getClaim('CLM-1')).rejects.toThrow('Forbidden');
    });
  });
});
