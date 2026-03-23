import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useThirdPartyPortal } from '../context/useThirdPartyPortal';
import {
  thirdPartyPortalApi,
  setThirdPartyPortalSession,
  clearThirdPartyPortalSession,
  type ThirdPartyPortalSession,
} from '../api/thirdPartyPortalClient';

function parseHashParams(): Record<string, string> {
  if (typeof window === 'undefined') return {};
  const raw = window.location.hash.replace(/^#/, '');
  if (!raw) return {};
  return Object.fromEntries(new URLSearchParams(raw).entries());
}

export default function ThirdPartyPortalLogin() {
  const navigate = useNavigate();
  const { login } = useThirdPartyPortal();
  const [claimId, setClaimId] = useState('');
  const [token, setToken] = useState('');
  const [showToken, setShowToken] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const fromHash = parseHashParams();
    const sp = new URLSearchParams(window.location.search);
    const qClaim = sp.get('claim_id');
    const qToken = sp.get('token');

    if (fromHash.claim_id) setClaimId(fromHash.claim_id);
    else if (qClaim) setClaimId(qClaim);

    if (fromHash.token) setToken(fromHash.token);
    else if (qToken) setToken(qToken);

    const spClean = new URLSearchParams(window.location.search);
    const hadQueryToken = spClean.has('token');
    if (hadQueryToken) spClean.delete('token');
    const nextSearch = spClean.toString();
    const pathBase = window.location.pathname + (nextSearch ? `?${nextSearch}` : '');
    if (window.location.hash.length > 1 || hadQueryToken) {
      window.history.replaceState(null, '', pathBase);
    }
  }, []);

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
    const creds: ThirdPartyPortalSession = { claimId: cid, token: tok };
    try {
      setThirdPartyPortalSession(creds);
      await thirdPartyPortalApi.getClaim(cid);
      login(creds);
      navigate(`/third-party-portal/claims/${encodeURIComponent(cid)}`, { replace: true });
    } catch (err) {
      clearThirdPartyPortalSession();
      setError(err instanceof Error ? err.message : 'Verification failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-gray-900/80 rounded-2xl border border-gray-700/50 p-8 shadow-xl">
        <h1 className="text-2xl font-bold text-gray-100 mb-1">Third-Party Portal</h1>
        <p className="text-sm text-gray-400 mb-6">
          Limited claim access for counterparties. Sign in with the claim ID and token from the
          carrier.
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
              className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-gray-200 placeholder:text-gray-500 focus:outline-none focus:ring-1 focus:ring-purple-500/40 font-mono text-sm"
              placeholder="e.g. CLM-..."
              autoComplete="off"
            />
          </div>
          <div>
            <div className="flex items-center justify-between gap-2 mb-1">
              <label className="block text-xs text-gray-400">Access Token</label>
              <button
                type="button"
                onClick={() => setShowToken((v) => !v)}
                className="text-[10px] uppercase tracking-wide text-purple-500/90 hover:text-purple-400"
              >
                {showToken ? 'Hide' : 'Show'}
              </button>
            </div>
            <input
              type={showToken ? 'text' : 'password'}
              value={token}
              onChange={(e) => setToken(e.target.value)}
              className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-gray-200 placeholder:text-gray-500 focus:outline-none focus:ring-1 focus:ring-purple-500/40 font-mono text-sm"
              placeholder="Paste token from the carrier"
              autoComplete="off"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 bg-purple-600 text-white font-medium rounded-lg hover:bg-purple-500 disabled:opacity-50 transition-colors"
          >
            {loading ? 'Verifying...' : 'Sign In'}
          </button>
        </form>

        <p className="mt-6 text-xs text-gray-500 text-center leading-relaxed">
          Deep link (recommended): append{' '}
          <span className="font-mono text-gray-400">#claim_id=CLM-...&token=...</span> so the token
          stays in the fragment. You may use{' '}
          <span className="font-mono text-gray-400">?claim_id=...</span> in the query string; a legacy{' '}
          <span className="font-mono text-gray-400">?token=...</span> is read once then stripped.
        </p>
      </div>
    </div>
  );
}
