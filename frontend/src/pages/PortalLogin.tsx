import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { usePortal } from '../context/usePortal';
import { useRepairPortal } from '../context/useRepairPortal';
import {
  portalApi,
  setPortalSession,
  clearPortalSession,
  type PortalSession,
} from '../api/portalClient';
import {
  repairPortalApi,
  setRepairPortalSession,
  clearRepairPortalSession,
  type RepairPortalSession,
} from '../api/repairPortalClient';

type PortalRole = 'claimant' | 'repair_shop';
type ClaimantMode = 'policy' | 'token';

function parseHashParams(): Record<string, string> {
  if (typeof window === 'undefined') return {};
  const raw = window.location.hash.replace(/^#/, '');
  if (!raw) return {};
  return Object.fromEntries(new URLSearchParams(raw).entries());
}

export default function PortalLogin() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { login: claimantLogin } = usePortal();
  const { login: repairLogin } = useRepairPortal();

  // Role selector
  const [role, setRole] = useState<PortalRole>('claimant');

  // Claimant-specific state
  const [claimantMode, setClaimantMode] = useState<ClaimantMode>('policy');
  const [claimantToken, setClaimantToken] = useState('');
  const [policyNumber, setPolicyNumber] = useState('');
  const [vin, setVin] = useState('');

  // Repair-shop state
  const [shopClaimId, setShopClaimId] = useState('');
  const [shopToken, setShopToken] = useState('');
  const [showShopToken, setShowShopToken] = useState(false);

  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Auto-populate from URL params (magic-link support)
  useEffect(() => {
    const fromHash = parseHashParams();
    const sp = searchParams;
    const qClaim = sp.get('claim_id');
    const qToken = sp.get('token');
    const qRole = sp.get('role') as PortalRole | null;

    if (qRole === 'repair_shop') setRole('repair_shop');

    const t = fromHash.token || qToken || '';
    const cid = fromHash.claim_id || qClaim || '';

    // Fragment deep-link (repair shop): #claim_id=...&token=... (token stays off query string)
    if (fromHash.claim_id && fromHash.token) {
      setShopClaimId(fromHash.claim_id);
      setShopToken(fromHash.token);
      setRole('repair_shop');
    } else if (qRole === 'repair_shop' && cid && t) {
      // Query-string repair link must include role=repair_shop so claimant ?claim_id=&token= bookmarks keep working
      setShopClaimId(cid);
      setShopToken(t);
      setRole('repair_shop');
    } else if (t && qRole === 'repair_shop' && !cid) {
      setShopToken(t);
    } else if (t) {
      // Claimant magic link (?token= or ?claim_id=&token= without repair role)
      setClaimantToken(t);
      setClaimantMode('token');
    }

    // Strip sensitive token parameters from the query string and fragment.
    // The token should only exist in memory after this point.
    const spClean = new URLSearchParams(window.location.search);
    const hadQToken = spClean.has('token');
    const hadQClaimId = spClean.has('claim_id');
    if (hadQToken) spClean.delete('token');
    if (hadQClaimId) spClean.delete('claim_id');
    const nextSearch = spClean.toString();
    const pathBase = window.location.pathname + (nextSearch ? `?${nextSearch}` : '');
    if (window.location.hash.length > 1 || hadQToken || hadQClaimId) {
      window.history.replaceState(null, '', pathBase);
    }
  }, [searchParams]);

  // -----------------------------------------------------------------------
  // Claimant submit
  // -----------------------------------------------------------------------
  async function handleClaimantSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      let creds: PortalSession;
      if (claimantMode === 'token') {
        if (!claimantToken.trim()) {
          setError('Access token is required');
          return;
        }
        creds = { token: claimantToken.trim() };
      } else {
        if (!policyNumber.trim() || !vin.trim()) {
          setError('Policy number and VIN are required');
          return;
        }
        creds = { policyNumber: policyNumber.trim(), vin: vin.trim() };
      }
      setPortalSession(creds);
      const { claims } = await portalApi.getClaims({ limit: 1 });
      if (claims.length === 0) {
        clearPortalSession();
        setError('No claims found. Please check your information.');
        return;
      }
      claimantLogin(creds);
      navigate('/portal/claims', { replace: true });
    } catch (err) {
      clearPortalSession();
      setError(err instanceof Error ? err.message : 'Verification failed');
    } finally {
      setLoading(false);
    }
  }

  // -----------------------------------------------------------------------
  // Repair-shop submit
  // -----------------------------------------------------------------------
  async function handleRepairShopSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const cid = shopClaimId.trim();
    const tok = shopToken.trim();
    if (!cid || !tok) {
      setError('Claim ID and access token are required');
      return;
    }
    setLoading(true);
    const creds: RepairPortalSession = { claimId: cid, token: tok };
    try {
      setRepairPortalSession(creds);
      await repairPortalApi.getClaim(cid);
      repairLogin(creds);
      navigate(`/repair-portal/claims/${encodeURIComponent(cid)}`, { replace: true });
    } catch (err) {
      clearRepairPortalSession();
      setError(err instanceof Error ? err.message : 'Verification failed');
    } finally {
      setLoading(false);
    }
  }

  // -----------------------------------------------------------------------
  // Render helpers
  // -----------------------------------------------------------------------
  const claimantSubBtnClass = (active: boolean) =>
    active
      ? 'bg-emerald-600 text-white'
      : 'bg-gray-800 text-gray-400 hover:bg-gray-700';

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-gray-900/80 rounded-2xl border border-gray-700/50 p-8 shadow-xl">
        {/* Portal-type selector */}
        <div className="flex gap-2 mb-6">
          <button
            type="button"
            onClick={() => { setRole('claimant'); setError(null); }}
            className={`flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-colors ${
              role === 'claimant'
                ? 'bg-emerald-600 text-white'
                : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
            }`}
          >
            Policyholder
          </button>
          <button
            type="button"
            onClick={() => { setRole('repair_shop'); setError(null); }}
            className={`flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-colors ${
              role === 'repair_shop'
                ? 'bg-amber-600 text-white'
                : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
            }`}
          >
            Repair Shop
          </button>
        </div>

        {role === 'claimant' ? (
          <>
            <h1 className="text-2xl font-bold text-gray-100 mb-1">Claimant Portal</h1>
            <p className="text-sm text-gray-400 mb-6">
              Sign in to view your claims and upload documents
            </p>

            {error && (
              <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
                {error}
              </div>
            )}

            <form onSubmit={handleClaimantSubmit} className="space-y-4">
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setClaimantMode('policy')}
                  className={`flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-colors ${claimantSubBtnClass(claimantMode === 'policy')}`}
                >
                  Policy & VIN
                </button>
                <button
                  type="button"
                  onClick={() => setClaimantMode('token')}
                  className={`flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-colors ${claimantSubBtnClass(claimantMode === 'token')}`}
                >
                  Access Token
                </button>
              </div>

              {claimantMode === 'policy' ? (
                <>
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">Policy Number</label>
                    <input
                      type="text"
                      value={policyNumber}
                      onChange={(e) => setPolicyNumber(e.target.value)}
                      className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-gray-200 placeholder:text-gray-500 focus:outline-none focus:ring-1 focus:ring-emerald-500/40"
                      placeholder="e.g. POL-12345"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400 mb-1">VIN</label>
                    <input
                      type="text"
                      value={vin}
                      onChange={(e) => setVin(e.target.value)}
                      className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-gray-200 placeholder:text-gray-500 focus:outline-none focus:ring-1 focus:ring-emerald-500/40"
                      placeholder="17-character vehicle ID"
                    />
                  </div>
                </>
              ) : (
                <div>
                  <label className="block text-xs text-gray-400 mb-1">Access Token</label>
                  <input
                    type="text"
                    value={claimantToken}
                    onChange={(e) => setClaimantToken(e.target.value)}
                    className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-gray-200 placeholder:text-gray-500 focus:outline-none focus:ring-1 focus:ring-emerald-500/40 font-mono text-sm"
                    placeholder="Paste token from email or link"
                  />
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="w-full py-3 bg-emerald-600 text-white font-medium rounded-lg hover:bg-emerald-500 disabled:opacity-50 transition-colors"
              >
                {loading ? 'Verifying...' : 'Sign In'}
              </button>
            </form>

            <p className="mt-6 text-xs text-gray-500 text-center">
              Use the access token from your claim confirmation email, or enter
              your policy number and VIN to view your claims.
            </p>
          </>
        ) : (
          <>
            <h1 className="text-2xl font-bold text-gray-100 mb-1">Repair Shop Portal</h1>
            <p className="text-sm text-gray-400 mb-6">
              Sign in with the claim ID and access token provided by the carrier
            </p>

            {error && (
              <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
                {error}
              </div>
            )}

            <form onSubmit={handleRepairShopSubmit} className="space-y-4">
              <div>
                <label className="block text-xs text-gray-400 mb-1">Claim ID</label>
                <input
                  type="text"
                  value={shopClaimId}
                  onChange={(e) => setShopClaimId(e.target.value)}
                  className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-gray-200 placeholder:text-gray-500 focus:outline-none focus:ring-1 focus:ring-amber-500/40 font-mono text-sm"
                  placeholder="e.g. CLM-..."
                  autoComplete="off"
                />
              </div>
              <div>
                <div className="flex items-center justify-between gap-2 mb-1">
                  <label className="block text-xs text-gray-400">Access Token</label>
                  <button
                    type="button"
                    onClick={() => setShowShopToken((v) => !v)}
                    className="text-[10px] uppercase tracking-wide text-amber-500/90 hover:text-amber-400"
                  >
                    {showShopToken ? 'Hide' : 'Show'}
                  </button>
                </div>
                <input
                  type={showShopToken ? 'text' : 'password'}
                  value={shopToken}
                  onChange={(e) => setShopToken(e.target.value)}
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

            <p className="mt-6 text-xs text-gray-500 text-center leading-relaxed">
              Deep link (recommended): append{' '}
              <span className="font-mono text-gray-400">#claim_id=CLM-...&token=...</span> so the
              token stays in the fragment and is not logged by referrers.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
