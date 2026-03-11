import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  setAuthToken,
  clearAuthToken,
  getClaimsStats,
  getClaims,
  getClaim,
  getClaimHistory,
  getClaimWorkflows,
  getDocs,
  getDoc,
  getSkills,
  getSkill,
  getSystemConfig,
  getSystemHealth,
  getAgentsCatalog,
  processClaimAsync,
  streamClaimUpdates,
} from './client';

const mockFetch = vi.fn();

describe('API client', () => {
  beforeEach(() => {
    mockFetch.mockReset();
    vi.stubGlobal('fetch', mockFetch);
    clearAuthToken();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('sends request to correct base URL', async () => {
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
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      text: async () => 'Not found',
    } as Response);

    await expect(getClaimsStats()).rejects.toThrow(/API error 404/);
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('retries once on 5xx error', async () => {
    vi.useFakeTimers();
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

    const pending = getClaimsStats();
    await vi.advanceTimersByTimeAsync(500);
    const result = await pending;

    expect(mockFetch).toHaveBeenCalledTimes(2);
    expect(result).toEqual({ total_claims: 0, by_status: {}, by_type: {} });
    vi.useRealTimers();
  });

  it('getClaims builds query string from params', async () => {
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

  it('getClaimHistory fetches history by id', async () => {
    const mockHistory = { claim_id: 'CLM-001', history: [], total: 0, limit: null, offset: 0 };
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockHistory,
    } as Response);

    const result = await getClaimHistory('CLM-001');

    expect(mockFetch).toHaveBeenCalledWith('/api/claims/CLM-001/history', expect.any(Object));
    expect(result).toEqual(mockHistory);
  });

  it('getClaimWorkflows fetches workflows by id', async () => {
    const mockWorkflows = { claim_id: 'CLM-001', workflows: [] };
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => mockWorkflows,
    } as Response);

    const result = await getClaimWorkflows('CLM-001');

    expect(mockFetch).toHaveBeenCalledWith('/api/claims/CLM-001/workflows', expect.any(Object));
    expect(result).toEqual(mockWorkflows);
  });

  it('getDocs fetches docs list', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ pages: [] }),
    } as Response);

    await getDocs();
    expect(mockFetch).toHaveBeenCalledWith('/api/docs', expect.any(Object));
  });

  it('getDoc fetches doc by slug', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ slug: 'intro', title: 'Intro', content: 'Hello' }),
    } as Response);

    await getDoc('intro');
    expect(mockFetch).toHaveBeenCalledWith('/api/docs/intro', expect.any(Object));
  });

  it('getSkills fetches skills list', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ groups: {} }),
    } as Response);

    await getSkills();
    expect(mockFetch).toHaveBeenCalledWith('/api/skills', expect.any(Object));
  });

  it('getSkill fetches skill by name', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ name: 'adjuster', role: 'Adjuster', content: '' }),
    } as Response);

    await getSkill('adjuster');
    expect(mockFetch).toHaveBeenCalledWith('/api/skills/adjuster', expect.any(Object));
  });

  it('getSystemConfig fetches config', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);

    await getSystemConfig();
    expect(mockFetch).toHaveBeenCalledWith('/api/system/config', expect.any(Object));
  });

  it('getSystemHealth fetches health', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ status: 'healthy', database: 'sqlite', total_claims: 0 }),
    } as Response);

    await getSystemHealth();
    expect(mockFetch).toHaveBeenCalledWith('/api/system/health', expect.any(Object));
  });

  it('getAgentsCatalog fetches agents', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ crews: [] }),
    } as Response);

    await getAgentsCatalog();
    expect(mockFetch).toHaveBeenCalledWith('/api/system/agents', expect.any(Object));
  });

  it('processClaimAsync sends multiple files', async () => {
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

  it('processClaimAsync throws on non-ok response', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 400,
      text: async () => 'Bad request',
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

    await expect(processClaimAsync(payload)).rejects.toThrow(/API error 400/);
  });

  describe('streamClaimUpdates', () => {
    function createStreamChunks(...chunks: string[]) {
      return new ReadableStream({
        start(controller) {
          for (const chunk of chunks) {
            controller.enqueue(new TextEncoder().encode(chunk));
          }
          controller.close();
        },
      });
    }

    it('calls onUpdate with parsed SSE data', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      body: createStreamChunks('data: {"claim":{"id":"CLM-1","status":"open"},"done":false}\n\n', 'data: {"done":true}\n\n'),
    } as Response);

    const onUpdate = vi.fn();
    const abort = streamClaimUpdates('CLM-1', onUpdate);

    await vi.waitFor(() => {
      expect(onUpdate).toHaveBeenCalledWith(
        expect.objectContaining({ claim: expect.objectContaining({ id: 'CLM-1' }), done: false })
      );
      expect(onUpdate).toHaveBeenCalledWith(expect.objectContaining({ done: true }));
    });

    abort();
    });

    it('calls onError when stream returns non-ok', async () => {
      vi.useFakeTimers();
      mockFetch.mockResolvedValue({
        ok: false,
        status: 500,
      } as Response);

      const onUpdate = vi.fn();
      const onError = vi.fn();
      const abort = streamClaimUpdates('CLM-1', onUpdate, onError);

      await vi.advanceTimersByTimeAsync(2000);
      await vi.advanceTimersByTimeAsync(4000);
      await vi.advanceTimersByTimeAsync(6000);

      expect(onError).toHaveBeenCalledWith(
        expect.objectContaining({ message: expect.stringContaining('Stream error 500') })
      );

      abort();
      vi.useRealTimers();
    });

    it('fetches correct stream URL with auth headers', async () => {
    setAuthToken('stream-token');
    mockFetch.mockResolvedValueOnce({
      ok: true,
      body: createStreamChunks('data: {"done":true}\n\n'),
    } as Response);

    const onUpdate = vi.fn();
    const abort = streamClaimUpdates('CLM-1', onUpdate);

    await vi.waitFor(() => {
      expect(onUpdate).toHaveBeenCalledWith(expect.objectContaining({ done: true }));
    });

    expect(mockFetch).toHaveBeenCalledWith(
      '/api/claims/CLM-1/stream',
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer stream-token',
        }),
      })
    );

    abort();
    clearAuthToken();
    });

    it('abort stops the stream without calling onError', async () => {
    mockFetch.mockImplementation(
      () =>
        new Promise((resolve) => {
          setTimeout(
            () =>
              resolve({
                ok: true,
                body: createStreamChunks('data: {"done":true}\n\n'),
              } as Response),
            100
          );
        })
    );

    const onUpdate = vi.fn();
    const onError = vi.fn();
    const abort = streamClaimUpdates('CLM-1', onUpdate, onError);

    abort();

    await new Promise((r) => setTimeout(r, 150));

    expect(onError).not.toHaveBeenCalled();
    });
  });
});
