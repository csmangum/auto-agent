import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useRepairPortal } from '../context/useRepairPortal';
import {
  repairPortalApi,
  setRepairPortalSession,
  clearRepairPortalSession,
  type RepairPortalSession,
} from '../api/repairPortalClient';

export default function RepairPortalLogin() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { login } = useRepairPortal();
  const [claimId, setClaimId] = useState(searchParams.get('claim_id') ?? '');
  const [token, setToken] = useState(searchParams.get('token') ?? '');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const cid = searchParams.get('claim_id');
    const t = searchParams.get('token');
    if (cid) setClaimId(cid);
    if (t) setToken(t);
  }, [searchParams]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const cid = claimId.trim();
    const tok = token.trim();
    if (!cid || !tok) {
      setError('Claim ID and access token are required');
      return;
    }
    setLoading(true);
    const creds: RepairPortalSession = { claimId: cid, token: tok };
    try {
      setRepairPortalSession(creds);
      await repairPortalApi.getClaim(cid);
      login(creds);
      navigate(`/repair-portal/claims/${encodeURIComponent(cid)}`, { replace: true });
    } catch (err) {
      clearRepairPortalSession();
      setError(err instanceof Error ? err.message : 'Verification failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-gray-900/80 rounded-2xl border border-gray-700/50 p-8 shadow-xl">
        <h1 className="text-2xl font-bold text-gray-100 mb-1">Repair Shop Portal</h1>
        <p className="text-sm text-gray-400 mb-6">
          Sign in with the claim ID and access token provided by the carrier
        </p>

        {error && (
          <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs text-gray-400 mb-1">Claim ID</label>
            <input
              type="text"
              value={claimId}
              onChange={(e) => setClaimId(e.target.value)}
              className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-gray-200 placeholder:text-gray-500 focus:outline-none focus:ring-1 focus:ring-amber-500/40 font-mono text-sm"
              placeholder="e.g. CLM-..."
              autoComplete="off"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">Access Token</label>
            <input
              type="text"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-gray-200 placeholder:text-gray-500 focus:outline-none focus:ring-1 focus:ring-amber-500/40 font-mono text-sm"
              placeholder="Paste token from the carrier"
              autoComplete="off"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 bg-amber-600 text-white font-medium rounded-lg hover:bg-amber-500 disabled:opacity-50 transition-colors"
          >
            {loading ? 'Verifying...' : 'Sign In'}
          </button>
        </form>

        <p className="mt-6 text-xs text-gray-500 text-center">
          Deep link: add <span className="font-mono text-gray-400">?claim_id=...&token=...</span> to
          this URL to prefill the form.
        </p>
      </div>
    </div>
  );
}
