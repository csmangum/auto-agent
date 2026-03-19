import { useState } from 'react';
import {
  useClaimPayments,
  useCreatePayment,
  useIssuePayment,
  useClearPayment,
  useVoidPayment,
} from '../api/queries';
import { formatDateTime } from '../utils/date';
import EmptyState from './EmptyState';
import type { ClaimPayment, PayeeType, PaymentMethod, PaymentStatusType } from '../api/types';

const PAYEE_TYPES: { value: PayeeType; label: string }[] = [
  { value: 'claimant', label: 'Claimant' },
  { value: 'repair_shop', label: 'Repair Shop' },
  { value: 'rental_company', label: 'Rental Company' },
  { value: 'medical_provider', label: 'Medical Provider' },
  { value: 'lienholder', label: 'Lienholder' },
  { value: 'attorney', label: 'Attorney' },
  { value: 'other', label: 'Other' },
];

const PAYMENT_METHODS: { value: PaymentMethod; label: string }[] = [
  { value: 'check', label: 'Check' },
  { value: 'ach', label: 'ACH' },
  { value: 'wire', label: 'Wire' },
  { value: 'card', label: 'Card' },
  { value: 'other', label: 'Other' },
];

const STATUS_STYLES: Record<PaymentStatusType, { bg: string; text: string; icon: string }> = {
  authorized: { bg: 'bg-blue-500/20', text: 'text-blue-400', icon: '🔵' },
  issued: { bg: 'bg-yellow-500/20', text: 'text-yellow-400', icon: '🟡' },
  cleared: { bg: 'bg-emerald-500/20', text: 'text-emerald-400', icon: '🟢' },
  voided: { bg: 'bg-red-500/20', text: 'text-red-400', icon: '🔴' },
};

function PaymentStatusBadge({ status }: { status: PaymentStatusType }) {
  const s = STATUS_STYLES[status] ?? STATUS_STYLES.authorized;
  return (
    <span className={`text-xs px-2 py-0.5 rounded ${s.bg} ${s.text} capitalize`}>
      {s.icon} {status}
    </span>
  );
}

interface PaymentPanelProps {
  claimId: string;
}

function CreatePaymentForm({ claimId, onDone }: { claimId: string; onDone: () => void }) {
  const [amount, setAmount] = useState('');
  const [payee, setPayee] = useState('');
  const [payeeType, setPayeeType] = useState<PayeeType>('claimant');
  const [method, setMethod] = useState<PaymentMethod>('check');
  const [checkNumber, setCheckNumber] = useState('');
  const [payeeSecondary, setPayeeSecondary] = useState('');
  const [payeeSecondaryType, setPayeeSecondaryType] = useState<PayeeType>('lienholder');

  const createMutation = useCreatePayment(claimId);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const num = parseFloat(amount);
    if (Number.isNaN(num) || num <= 0 || !payee.trim()) return;
    createMutation.mutate(
      {
        claim_id: claimId,
        amount: num,
        payee: payee.trim(),
        payee_type: payeeType,
        payment_method: method,
        ...(checkNumber.trim() && { check_number: checkNumber.trim() }),
        ...(payeeSecondary.trim() && { payee_secondary: payeeSecondary.trim(), payee_secondary_type: payeeSecondaryType }),
      },
      {
        onSuccess: () => {
          setAmount('');
          setPayee('');
          setCheckNumber('');
          setPayeeSecondary('');
          onDone();
        },
      }
    );
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4 bg-gray-900/50 rounded-lg p-4 ring-1 ring-gray-700/50">
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs text-gray-500 mb-1">Amount ($) *</label>
          <input
            type="number"
            min="0.01"
            step="0.01"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            required
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
            placeholder="e.g. 2500.00"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Payment Method *</label>
          <select
            value={method}
            onChange={(e) => setMethod(e.target.value as PaymentMethod)}
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            {PAYMENT_METHODS.map((m) => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs text-gray-500 mb-1">Payee *</label>
          <input
            type="text"
            value={payee}
            onChange={(e) => setPayee(e.target.value)}
            required
            maxLength={500}
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
            placeholder="Payee name"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Payee Type *</label>
          <select
            value={payeeType}
            onChange={(e) => setPayeeType(e.target.value as PayeeType)}
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            {PAYEE_TYPES.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
        </div>
      </div>
      {method === 'check' && (
        <div>
          <label className="block text-xs text-gray-500 mb-1">Check Number</label>
          <input
            type="text"
            value={checkNumber}
            onChange={(e) => setCheckNumber(e.target.value)}
            maxLength={100}
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
            placeholder="Optional check number"
          />
        </div>
      )}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs text-gray-500 mb-1">Secondary Payee</label>
          <input
            type="text"
            value={payeeSecondary}
            onChange={(e) => setPayeeSecondary(e.target.value)}
            maxLength={500}
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
            placeholder="Optional (e.g. lienholder)"
          />
        </div>
        {payeeSecondary.trim() && (
          <div>
            <label className="block text-xs text-gray-500 mb-1">Secondary Type</label>
            <select
              value={payeeSecondaryType}
              onChange={(e) => setPayeeSecondaryType(e.target.value as PayeeType)}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              {PAYEE_TYPES.map((p) => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
          </div>
        )}
      </div>
      <div className="flex gap-2 justify-end">
        <button type="button" onClick={onDone} className="px-3 py-1.5 text-sm text-gray-400 hover:text-gray-200 transition-colors">
          Cancel
        </button>
        <button
          type="submit"
          disabled={createMutation.isPending || !amount || !payee.trim()}
          className="px-4 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {createMutation.isPending ? 'Creating…' : 'Create Payment'}
        </button>
      </div>
      {createMutation.isError && (
        <p className="text-xs text-red-400">
          {createMutation.error instanceof Error ? createMutation.error.message : 'Failed to create payment'}
        </p>
      )}
    </form>
  );
}

function PaymentActions({ payment, claimId }: { payment: ClaimPayment; claimId: string }) {
  const [voidReason, setVoidReason] = useState('');
  const [showVoid, setShowVoid] = useState(false);

  const issueMutation = useIssuePayment(claimId);
  const clearMutation = useClearPayment(claimId);
  const voidMutation = useVoidPayment(claimId);

  const loading = issueMutation.isPending || clearMutation.isPending || voidMutation.isPending;

  if (payment.status === 'cleared' || payment.status === 'voided') return null;

  return (
    <div className="flex items-center gap-2 flex-wrap">
      {payment.status === 'authorized' && (
        <button
          onClick={() => issueMutation.mutate({ paymentId: payment.id })}
          disabled={loading}
          className="px-2.5 py-1 text-xs bg-yellow-600/80 text-white rounded hover:bg-yellow-500 disabled:opacity-50 transition-colors"
        >
          Issue
        </button>
      )}
      {payment.status === 'issued' && (
        <button
          onClick={() => clearMutation.mutate(payment.id)}
          disabled={loading}
          className="px-2.5 py-1 text-xs bg-emerald-600/80 text-white rounded hover:bg-emerald-500 disabled:opacity-50 transition-colors"
        >
          Clear
        </button>
      )}
      {(payment.status === 'authorized' || payment.status === 'issued') && (
        showVoid ? (
          <div className="flex items-center gap-1">
            <input
              type="text"
              value={voidReason}
              onChange={(e) => setVoidReason(e.target.value)}
              placeholder="Reason..."
              className="w-32 bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-gray-200 focus:outline-none focus:ring-1 focus:ring-red-500"
              autoFocus
            />
            <button
              onClick={() => {
                voidMutation.mutate(
                  { paymentId: payment.id, reason: voidReason || undefined },
                  { onSuccess: () => { setShowVoid(false); setVoidReason(''); } }
                );
              }}
              disabled={loading}
              className="px-2 py-1 text-xs bg-red-600/80 text-white rounded hover:bg-red-500 disabled:opacity-50 transition-colors"
            >
              Confirm
            </button>
            <button
              onClick={() => { setShowVoid(false); setVoidReason(''); }}
              className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
            >
              ✕
            </button>
          </div>
        ) : (
          <button
            onClick={() => setShowVoid(true)}
            disabled={loading}
            className="px-2.5 py-1 text-xs bg-red-600/80 text-white rounded hover:bg-red-500 disabled:opacity-50 transition-colors"
          >
            Void
          </button>
        )
      )}
    </div>
  );
}

export default function PaymentPanel({ claimId }: PaymentPanelProps) {
  const [showForm, setShowForm] = useState(false);
  const { data, isLoading, error } = useClaimPayments(claimId);
  const payments = data?.payments ?? [];

  // Summaries
  const totals = payments.reduce(
    (acc, p) => {
      if (p.status === 'authorized') acc.authorized += p.amount;
      if (p.status === 'issued') acc.issued += p.amount;
      if (p.status === 'cleared') acc.cleared += p.amount;
      if (p.status === 'voided') acc.voided += p.amount;
      return acc;
    },
    { authorized: 0, issued: 0, cleared: 0, voided: 0 }
  );

  return (
    <div className="space-y-6">
      {/* Summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="bg-blue-500/10 rounded-lg p-3 ring-1 ring-blue-500/20">
          <p className="text-xs text-blue-400 font-medium">Authorized</p>
          <p className="text-lg font-bold text-gray-100 mt-1">${totals.authorized.toLocaleString()}</p>
        </div>
        <div className="bg-yellow-500/10 rounded-lg p-3 ring-1 ring-yellow-500/20">
          <p className="text-xs text-yellow-400 font-medium">Issued</p>
          <p className="text-lg font-bold text-gray-100 mt-1">${totals.issued.toLocaleString()}</p>
        </div>
        <div className="bg-emerald-500/10 rounded-lg p-3 ring-1 ring-emerald-500/20">
          <p className="text-xs text-emerald-400 font-medium">Cleared</p>
          <p className="text-lg font-bold text-gray-100 mt-1">${totals.cleared.toLocaleString()}</p>
        </div>
        <div className="bg-red-500/10 rounded-lg p-3 ring-1 ring-red-500/20">
          <p className="text-xs text-red-400 font-medium">Voided</p>
          <p className="text-lg font-bold text-gray-100 mt-1">${totals.voided.toLocaleString()}</p>
        </div>
      </div>

      {/* Create payment */}
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-gray-300">Payments</h3>
          <button
            onClick={() => setShowForm(!showForm)}
            className="px-3 py-1 text-xs bg-blue-600/80 text-white rounded hover:bg-blue-500 transition-colors"
          >
            {showForm ? 'Cancel' : '+ New Payment'}
          </button>
        </div>

        {showForm && (
          <div className="mb-4">
            <CreatePaymentForm claimId={claimId} onDone={() => setShowForm(false)} />
          </div>
        )}

        {error && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-3 mb-4">
            <p className="text-sm text-red-400">{error instanceof Error ? error.message : 'Failed to load payments'}</p>
          </div>
        )}

        {isLoading ? (
          <div className="space-y-3">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-16 bg-gray-700/30 rounded skeleton-shimmer" />
            ))}
          </div>
        ) : payments.length === 0 ? (
          <EmptyState
            icon="💳"
            title="No payments"
            description="No payments have been created for this claim."
          />
        ) : (
          <div className="space-y-3">
            {payments.map((payment) => (
              <div
                key={payment.id}
                className="rounded-lg bg-gray-900/50 p-4 ring-1 ring-gray-700/50"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-lg font-bold text-gray-100">
                        ${payment.amount.toLocaleString()}
                      </span>
                      <PaymentStatusBadge status={payment.status} />
                      <span className="text-xs text-gray-500 capitalize">
                        {payment.payment_method}
                      </span>
                    </div>
                    <p className="text-sm text-gray-300">
                      {payment.payee}
                      <span className="text-gray-500 text-xs ml-1">
                        ({payment.payee_type.replace(/_/g, ' ')})
                      </span>
                    </p>
                    {payment.payee_secondary && (
                      <p className="text-xs text-gray-500 mt-0.5">
                        Secondary: {payment.payee_secondary}
                      </p>
                    )}
                    {payment.check_number && (
                      <p className="text-xs text-gray-500 mt-0.5">
                        Check #: {payment.check_number}
                      </p>
                    )}
                    {payment.void_reason && (
                      <p className="text-xs text-red-400 mt-1">
                        Void reason: {payment.void_reason}
                      </p>
                    )}
                    <div className="flex items-center gap-3 mt-2 text-xs text-gray-600">
                      <span>Auth: {payment.authorized_by}</span>
                      <span>{formatDateTime(payment.created_at)}</span>
                      {payment.issued_at && <span>Issued: {formatDateTime(payment.issued_at)}</span>}
                      {payment.cleared_at && <span>Cleared: {formatDateTime(payment.cleared_at)}</span>}
                    </div>
                  </div>
                  <PaymentActions payment={payment} claimId={claimId} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
