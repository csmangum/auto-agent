import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { waitFor } from '@testing-library/react';
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

    await waitFor(() => {
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

    await waitFor(() => {
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
      (_url, options) =>
        new Promise((resolve, reject) => {
          const signal = options?.signal as AbortSignal;
          const timeoutId = setTimeout(
            () =>
              resolve({
                ok: true,
                body: createStreamChunks('data: {"done":true}\n\n'),
              } as Response),
            100
          );
          if (signal) {
            signal.addEventListener('abort', () => {
              clearTimeout(timeoutId);
              reject(new DOMException('Aborted', 'AbortError'));
            });
          }
        })
    );

    const onUpdate = vi.fn();
    const onError = vi.fn();
    const abort = streamClaimUpdates('CLM-1', onUpdate, onError);

    abort();

    await new Promise((r) => setTimeout(r, 150));

    expect(onError).not.toHaveBeenCalled();
    expect(onUpdate).not.toHaveBeenCalled();
    });
  });

  describe('additional API functions', () => {
    it('getClaimReserveHistory', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ history: [] }) } as Response);
      const { getClaimReserveHistory } = await import('./client');
      await getClaimReserveHistory('CLM-1', 25);
      expect(mockFetch).toHaveBeenCalledWith('/api/claims/CLM-1/reserve-history?limit=25', expect.any(Object));
    });

    it('getClaimReserveAdequacy', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ adequate: true, warnings: [] }) } as Response);
      const { getClaimReserveAdequacy } = await import('./client');
      await getClaimReserveAdequacy('CLM-1');
      expect(mockFetch).toHaveBeenCalledWith('/api/claims/CLM-1/reserve/adequacy', expect.any(Object));
    });

    it('patchClaimReserve', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ claim_id: 'CLM-1', reserve_amount: 5000 }) } as Response);
      const { patchClaimReserve } = await import('./client');
      await patchClaimReserve('CLM-1', { reserve_amount: 5000 });
      expect(mockFetch).toHaveBeenCalledWith('/api/claims/CLM-1/reserve', expect.objectContaining({ method: 'PATCH' }));
    });

    it('getCostBreakdown', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ total_cost_usd: 0 }) } as Response);
      const { getCostBreakdown } = await import('./client');
      await getCostBreakdown();
      expect(mockFetch).toHaveBeenCalledWith('/api/metrics/cost', expect.any(Object));
    });

    it('getPolicies', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ policies: [] }) } as Response);
      const { getPolicies } = await import('./client');
      await getPolicies();
      expect(mockFetch).toHaveBeenCalledWith('/api/system/policies', expect.any(Object));
    });

    it('generateIncidentDetails', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ incident_date: '2025-01-01' }) } as Response);
      const { generateIncidentDetails } = await import('./client');
      await generateIncidentDetails({ vehicle_year: 2022, vehicle_make: 'Honda', vehicle_model: 'Accord' });
      expect(mockFetch).toHaveBeenCalledWith('/api/claims/generate-incident-details', expect.objectContaining({ method: 'POST' }));
    });

    it('postClaimDispute', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ resolution_type: 'pending' }) } as Response);
      const { postClaimDispute } = await import('./client');
      await postClaimDispute('CLM-1', { dispute_type: 'liability', dispute_description: 'disagree' });
      expect(mockFetch).toHaveBeenCalledWith('/api/claims/CLM-1/dispute', expect.objectContaining({ method: 'POST' }));
    });

    it('postClaimSupplemental', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ supplemental_amount: 500 }) } as Response);
      const { postClaimSupplemental } = await import('./client');
      await postClaimSupplemental('CLM-1', { supplemental_damage_description: 'hidden rust', reported_by: 'shop' });
      expect(mockFetch).toHaveBeenCalledWith('/api/claims/CLM-1/supplemental', expect.objectContaining({ method: 'POST' }));
    });

    it('getClaimRepairStatus', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ latest: null, history: [] }) } as Response);
      const { getClaimRepairStatus } = await import('./client');
      await getClaimRepairStatus('CLM-1');
      expect(mockFetch).toHaveBeenCalledWith('/api/claims/CLM-1/repair-status', expect.any(Object));
    });

    it('postClaimRepairStatus', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ ok: true, repair_status_id: 1 }) } as Response);
      const { postClaimRepairStatus } = await import('./client');
      await postClaimRepairStatus('CLM-1', { status: 'received' });
      expect(mockFetch).toHaveBeenCalledWith('/api/claims/CLM-1/repair-status', expect.objectContaining({ method: 'POST' }));
    });

    it('postClaimFollowUpResponse', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ success: true }) } as Response);
      const { postClaimFollowUpResponse } = await import('./client');
      await postClaimFollowUpResponse('CLM-1', { message_id: 1, response_content: 'got it' });
      expect(mockFetch).toHaveBeenCalledWith('/api/claims/CLM-1/follow-up/record-response', expect.objectContaining({ method: 'POST' }));
    });

    it('getClaimTasks', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ tasks: [] }) } as Response);
      const { getClaimTasks } = await import('./client');
      await getClaimTasks('CLM-1');
      expect(mockFetch).toHaveBeenCalledWith('/api/claims/CLM-1/tasks', expect.any(Object));
    });

    it('createClaimTask', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ id: 1 }) } as Response);
      const { createClaimTask } = await import('./client');
      await createClaimTask('CLM-1', { title: 'Review', task_type: 'review' });
      expect(mockFetch).toHaveBeenCalledWith('/api/claims/CLM-1/tasks', expect.objectContaining({ method: 'POST' }));
    });

    it('getAllTasks with params', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ tasks: [], total: 0 }) } as Response);
      const { getAllTasks } = await import('./client');
      await getAllTasks({ status: 'open', limit: 10 });
      expect(mockFetch).toHaveBeenCalledWith('/api/tasks?status=open&limit=10', expect.any(Object));
    });

    it('getTaskStats', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ total: 0, by_status: {} }) } as Response);
      const { getTaskStats } = await import('./client');
      await getTaskStats();
      expect(mockFetch).toHaveBeenCalledWith('/api/tasks/stats', expect.any(Object));
    });

    it('getTask', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ id: 1 }) } as Response);
      const { getTask } = await import('./client');
      await getTask(1);
      expect(mockFetch).toHaveBeenCalledWith('/api/tasks/1', expect.any(Object));
    });

    it('updateTask', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ id: 1 }) } as Response);
      const { updateTask } = await import('./client');
      await updateTask(1, { status: 'completed' });
      expect(mockFetch).toHaveBeenCalledWith('/api/tasks/1', expect.objectContaining({ method: 'PATCH' }));
    });

    it('getReviewQueue with params', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ claims: [], total: 0 }) } as Response);
      const { getReviewQueue } = await import('./client');
      await getReviewQueue({ assignee: 'admin', limit: 5 });
      expect(mockFetch).toHaveBeenCalledWith('/api/claims/review-queue?assignee=admin&limit=5', expect.any(Object));
    });

    it('assignClaim', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ claim_id: 'CLM-1', assignee: 'admin' }) } as Response);
      const { assignClaim } = await import('./client');
      await assignClaim('CLM-1', 'admin');
      expect(mockFetch).toHaveBeenCalledWith('/api/claims/CLM-1/assign', expect.objectContaining({ method: 'PATCH' }));
    });

    it('getClaimPayments', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ payments: [] }) } as Response);
      const { getClaimPayments } = await import('./client');
      await getClaimPayments('CLM-1');
      expect(mockFetch).toHaveBeenCalledWith('/api/claims/CLM-1/payments', expect.any(Object));
    });

    it('createPayment', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ id: 1 }) } as Response);
      const { createPayment } = await import('./client');
      await createPayment('CLM-1', { claim_id: 'CLM-1', amount: 1000, payee: 'John', payee_type: 'claimant', payment_method: 'check' });
      expect(mockFetch).toHaveBeenCalledWith('/api/claims/CLM-1/payments', expect.objectContaining({ method: 'POST' }));
    });

    it('issuePayment', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ id: 1 }) } as Response);
      const { issuePayment } = await import('./client');
      await issuePayment('CLM-1', 1);
      expect(mockFetch).toHaveBeenCalledWith('/api/claims/CLM-1/payments/1/issue', expect.objectContaining({ method: 'POST' }));
    });

    it('clearPayment', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ id: 1 }) } as Response);
      const { clearPayment } = await import('./client');
      await clearPayment('CLM-1', 1);
      expect(mockFetch).toHaveBeenCalledWith('/api/claims/CLM-1/payments/1/clear', expect.objectContaining({ method: 'POST' }));
    });

    it('voidPayment', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ id: 1 }) } as Response);
      const { voidPayment } = await import('./client');
      await voidPayment('CLM-1', 1, { reason: 'duplicate' });
      expect(mockFetch).toHaveBeenCalledWith('/api/claims/CLM-1/payments/1/void', expect.objectContaining({ method: 'POST' }));
    });

    it('getClaimDocuments with params', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ documents: [] }) } as Response);
      const { getClaimDocuments } = await import('./client');
      await getClaimDocuments('CLM-1', { document_type: 'estimate', group_by: 'storage_key' });
      expect(mockFetch).toHaveBeenCalledWith('/api/claims/CLM-1/documents?document_type=estimate&group_by=storage_key', expect.any(Object));
    });

    it('uploadClaimDocument', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ claim_id: 'CLM-1', document_id: 1, document: {} }) } as Response);
      const { uploadClaimDocument } = await import('./client');
      const file = new File(['data'], 'test.pdf', { type: 'application/pdf' });
      await uploadClaimDocument('CLM-1', file, { document_type: 'estimate', received_from: 'claimant' });
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/claims/CLM-1/documents?document_type=estimate&received_from=claimant',
        expect.objectContaining({ method: 'POST' })
      );
    });

    it('uploadClaimDocument rejects oversized files', async () => {
      const { uploadClaimDocument } = await import('./client');
      const bigFile = new File(['x'.repeat(100)], 'big.pdf', { type: 'application/pdf' });
      Object.defineProperty(bigFile, 'size', { value: 60 * 1024 * 1024 });
      await expect(uploadClaimDocument('CLM-1', bigFile)).rejects.toThrow(/maximum upload size/);
    });

    it('uploadClaimDocument rejects disallowed extensions', async () => {
      const { uploadClaimDocument } = await import('./client');
      const file = new File(['data'], 'script.exe', { type: 'application/octet-stream' });
      await expect(uploadClaimDocument('CLM-1', file)).rejects.toThrow(/File type not allowed/);
    });

    it('updateClaimDocument', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ document_id: 1 }) } as Response);
      const { updateClaimDocument } = await import('./client');
      await updateClaimDocument('CLM-1', 1, { review_status: 'approved' });
      expect(mockFetch).toHaveBeenCalledWith('/api/claims/CLM-1/documents/1', expect.objectContaining({ method: 'PATCH' }));
    });

    it('getDocumentRequests', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ requests: [] }) } as Response);
      const { getDocumentRequests } = await import('./client');
      await getDocumentRequests('CLM-1');
      expect(mockFetch).toHaveBeenCalledWith('/api/claims/CLM-1/document-requests', expect.any(Object));
    });

    it('createDocumentRequest', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ request_id: 1 }) } as Response);
      const { createDocumentRequest } = await import('./client');
      await createDocumentRequest('CLM-1', { document_type: 'police_report' });
      expect(mockFetch).toHaveBeenCalledWith('/api/claims/CLM-1/document-requests', expect.objectContaining({ method: 'POST' }));
    });

    it('addClaimNote', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ claim_id: 'CLM-1' }) } as Response);
      const { addClaimNote } = await import('./client');
      await addClaimNote('CLM-1', 'Test note', 'adjuster');
      expect(mockFetch).toHaveBeenCalledWith('/api/claims/CLM-1/notes', expect.objectContaining({ method: 'POST' }));
    });

    it('getOverdueTasks', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ tasks: [] }) } as Response);
      const { getOverdueTasks } = await import('./client');
      await getOverdueTasks(50);
      expect(mockFetch).toHaveBeenCalledWith('/api/tasks/overdue?limit=50', expect.any(Object));
    });

    it('getComplianceTemplates', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ templates: [] }) } as Response);
      const { getComplianceTemplates } = await import('./client');
      await getComplianceTemplates('CA');
      expect(mockFetch).toHaveBeenCalledWith('/api/diary/compliance-templates?state=CA', expect.any(Object));
    });

    it('createPartyRelationship', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ id: 1 }) } as Response);
      const { createPartyRelationship } = await import('./client');
      await createPartyRelationship('CLM-1', { from_party_id: 1, to_party_id: 2, relationship_type: 'represented_by' });
      expect(mockFetch).toHaveBeenCalledWith('/api/claims/CLM-1/party-relationships', expect.objectContaining({ method: 'POST' }));
    });

    it('deletePartyRelationship', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true } as Response);
      const { deletePartyRelationship } = await import('./client');
      await deletePartyRelationship('CLM-1', 10);
      expect(mockFetch).toHaveBeenCalledWith('/api/claims/CLM-1/party-relationships/10', expect.objectContaining({ method: 'DELETE' }));
    });

    it('getFraudReportingCompliance', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ reports: [] }) } as Response);
      const { getFraudReportingCompliance } = await import('./client');
      await getFraudReportingCompliance({ state: 'CA', limit: 10 });
      expect(mockFetch).toHaveBeenCalledWith('/api/compliance/fraud-reporting?state=CA&limit=10', expect.any(Object));
    });

    it('getCurrentUser', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ identity: 'admin', role: 'admin' }) } as Response);
      const { getCurrentUser } = await import('./client');
      const user = await getCurrentUser();
      expect(user).toEqual({ identity: 'admin', role: 'admin' });
    });

    it('getNoteTemplates', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ templates: [] }) } as Response);
      const { getNoteTemplates } = await import('./client');
      await getNoteTemplates({ activeOnly: true });
      expect(mockFetch).toHaveBeenCalledWith('/api/note-templates?active_only=true', expect.any(Object));
    });

    it('createNoteTemplate', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ id: 1, label: 'Test' }) } as Response);
      const { createNoteTemplate } = await import('./client');
      await createNoteTemplate({ label: 'Test', body: 'Template body' });
      expect(mockFetch).toHaveBeenCalledWith('/api/note-templates', expect.objectContaining({ method: 'POST' }));
    });

    it('updateNoteTemplate', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ id: 1 }) } as Response);
      const { updateNoteTemplate } = await import('./client');
      await updateNoteTemplate(1, { label: 'Updated' });
      expect(mockFetch).toHaveBeenCalledWith('/api/note-templates/1', expect.objectContaining({ method: 'PATCH' }));
    });

    it('deleteNoteTemplate', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true } as Response);
      const { deleteNoteTemplate } = await import('./client');
      await deleteNoteTemplate(1);
      expect(mockFetch).toHaveBeenCalledWith('/api/note-templates/1', expect.objectContaining({ method: 'DELETE' }));
    });

    it('getMetrics', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) } as Response);
      const { getMetrics } = await import('./client');
      await getMetrics();
      expect(mockFetch).toHaveBeenCalledWith('/api/metrics', expect.any(Object));
    });

    it('getClaimMetrics', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) } as Response);
      const { getClaimMetrics } = await import('./client');
      await getClaimMetrics('CLM-1');
      expect(mockFetch).toHaveBeenCalledWith('/api/metrics/CLM-1', expect.any(Object));
    });

    it('postJSON retries on 5xx', async () => {
      vi.useFakeTimers();
      mockFetch
        .mockResolvedValueOnce({ ok: false, status: 503, text: async () => 'down' } as Response)
        .mockResolvedValueOnce({ ok: true, json: async () => ({ ok: true }) } as Response);
      const { addClaimNote } = await import('./client');
      const pending = addClaimNote('CLM-1', 'note', 'actor');
      await vi.advanceTimersByTimeAsync(600);
      await pending;
      expect(mockFetch).toHaveBeenCalledTimes(2);
      vi.useRealTimers();
    });

    it('patchJSON retries on 5xx', async () => {
      vi.useFakeTimers();
      mockFetch
        .mockResolvedValueOnce({ ok: false, status: 500, text: async () => 'err' } as Response)
        .mockResolvedValueOnce({ ok: true, json: async () => ({ claim_id: 'CLM-1', reserve_amount: 1000 }) } as Response);
      const { patchClaimReserve } = await import('./client');
      const pending = patchClaimReserve('CLM-1', { reserve_amount: 1000 });
      await vi.advanceTimersByTimeAsync(600);
      await pending;
      expect(mockFetch).toHaveBeenCalledTimes(2);
      vi.useRealTimers();
    });

    it('deleteJSON retries on 5xx', async () => {
      vi.useFakeTimers();
      mockFetch
        .mockResolvedValueOnce({ ok: false, status: 502, text: async () => 'bad gw' } as Response)
        .mockResolvedValueOnce({ ok: true } as Response);
      const { deleteNoteTemplate } = await import('./client');
      const pending = deleteNoteTemplate(1);
      await vi.advanceTimersByTimeAsync(600);
      await pending;
      expect(mockFetch).toHaveBeenCalledTimes(2);
      vi.useRealTimers();
    });

    it('streamChat calls fetch with messages and emits events', async () => {
      function createStreamChunks(...chunks: string[]) {
        return new ReadableStream({
          start(controller) {
            for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk));
            controller.close();
          },
        });
      }
      mockFetch.mockResolvedValueOnce({
        ok: true,
        body: createStreamChunks('data: {"type":"text","content":"hello"}\n\n', 'data: {"type":"done"}\n\n'),
      } as Response);

      const { streamChat } = await import('./client');
      const onEvent = vi.fn();
      const abort = streamChat([{ role: 'user', content: 'hi' }], onEvent);

      await waitFor(() => {
        expect(onEvent).toHaveBeenCalledWith(expect.objectContaining({ type: 'text', content: 'hello' }));
        expect(onEvent).toHaveBeenCalledWith(expect.objectContaining({ type: 'done' }));
      });
      abort();
    });
  });
});
