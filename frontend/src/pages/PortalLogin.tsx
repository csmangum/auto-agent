import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { usePortal } from '../context/PortalContext';
import {
  portalApi,
  clearPortalSession,
} from '../api/portalClient';

export default function PortalLogin() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { login } = usePortal();
  const [mode, setMode] = useState<'token' | 'policy'>('policy');
  const [claimId, setClaimId] = useState(searchParams.get('claim_id') ?? '');
  const [token, setToken] = useState(searchParams.get('token') ?? '');
  const [policyNumber, setPolicyNumber] = useState('');
  const [vin, setVin] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const cid = searchParams.get('claim_id');
    const t = searchParams.get('token');
    if (cid && t) {
      setClaimId(cid);
      setToken(t);
      setMode('token');
    }
  }, [searchParams]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      if (mode === 'token') {
        if (!token.trim()) {
          setError('Access token is required');
          return;
        }
        login({ token: token.trim() });
      } else {
        if (!policyNumber.trim() || !vin.trim()) {
          setError('Policy number and VIN are required');
          return;
        }
        login({
          policyNumber: policyNumber.trim(),
          vin: vin.trim(),
        });
      }
      const { claims } = await portalApi.getClaims({ limit: 1 });
      if (claims.length === 0) {
        clearPortalSession();
        setError('No claims found. Please check your information.');
        return;
      }
      navigate('/portal/claims', { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Verification failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-gray-900/80 rounded-2xl border border-gray-700/50 p-8 shadow-xl">
        <h1 className="text-2xl font-bold text-gray-100 mb-1">
          Claimant Portal
        </h1>
        <p className="text-sm text-gray-400 mb-6">
          Sign in to view your claims and upload documents
        </p>

        {error && (
          <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setMode('policy')}
              className={`flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-colors ${
                mode === 'policy'
                  ? 'bg-emerald-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
              }`}
            >
              Policy & VIN
            </button>
            <button
              type="button"
              onClick={() => setMode('token')}
              className={`flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-colors ${
                mode === 'token'
                  ? 'bg-emerald-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
              }`}
            >
              Access Token
            </button>
          </div>

          {mode === 'policy' ? (
            <>
              <div>
                <label className="block text-xs text-gray-400 mb-1">
                  Policy Number
                </label>
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
            <>
              <div>
                <label className="block text-xs text-gray-400 mb-1">
                  Access Token
                </label>
                <input
                  type="text"
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-gray-200 placeholder:text-gray-500 focus:outline-none focus:ring-1 focus:ring-emerald-500/40 font-mono text-sm"
                  placeholder="Paste token from email or link"
                />
              </div>
            </>
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
      </div>
    </div>
  );
}
