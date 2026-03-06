import { useState, useEffect } from 'react';
import ClaimTable from '../components/ClaimTable';
import { getClaims } from '../api/client';

const STATUSES = [
  'pending', 'processing', 'open', 'closed', 'duplicate',
  'fraud_suspected', 'fraud_confirmed', 'needs_review',
  'partial_loss', 'under_investigation', 'denied', 'settled', 'disputed', 'failed',
];

const TYPES = ['new', 'duplicate', 'total_loss', 'fraud', 'partial_loss'];

export default function ClaimsList() {
  const [claims, setClaims] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [statusFilter, setStatusFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');

  useEffect(() => {
    setLoading(true);
    setError(null);
    const params = { limit: 200 };
    if (statusFilter) params.status = statusFilter;
    if (typeFilter) params.claim_type = typeFilter;

    getClaims(params)
      .then((data) => {
        setClaims(data.claims);
        setTotal(data.total);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [statusFilter, typeFilter]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Claims</h1>
        <p className="text-sm text-gray-500 mt-1">Browse and filter all claims in the system</p>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-4">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">All Statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s.replace(/_/g, ' ')}
            </option>
          ))}
        </select>

        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">All Types</option>
          {TYPES.map((t) => (
            <option key={t} value={t}>
              {t.replace(/_/g, ' ')}
            </option>
          ))}
        </select>

        <span className="self-center text-sm text-gray-500">
          {total} claim{total !== 1 ? 's' : ''}
        </span>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-red-800 text-sm">{error}</p>
        </div>
      )}

      {/* Claims table */}
      <div className="bg-white rounded-xl border border-gray-200">
        {loading ? (
          <div className="p-8 text-center">
            <div className="animate-pulse space-y-3">
              {[...Array(8)].map((_, i) => (
                <div key={i} className="h-10 bg-gray-100 rounded" />
              ))}
            </div>
          </div>
        ) : (
          <ClaimTable claims={claims} />
        )}
      </div>
    </div>
  );
}
