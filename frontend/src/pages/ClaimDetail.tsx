import { useState, useRef, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import type { UseMutationResult } from '@tanstack/react-query';
import PageHeader from '../components/PageHeader';
import StatusBadge from '../components/StatusBadge';
import TypeBadge from '../components/TypeBadge';
import AuditTimeline from '../components/AuditTimeline';
import EmptyState from '../components/EmptyState';
import StructuredOutputDisplay from '../components/StructuredOutputDisplay';
import TaskPanel from '../components/TaskPanel';
import PaymentPanel from '../components/PaymentPanel';
import CommunicationLog from '../components/CommunicationLog';
import CoverageSummary from '../components/CoverageSummary';
import DocumentVersionCompare from '../components/DocumentVersionCompare';
import {
  useClaim,
  useClaimHistory,
  useClaimReserveHistory,
  useClaimReserveAdequacy,
  useClaimWorkflows,
  usePatchClaimReserve,
  useAddClaimNote,
  useClaimDocuments,
  useUploadDocument,
  useUpdateDocument,
  useDocumentRequests,
  useCreateDocumentRequest,
  useCreatePartyRelationship,
  useDeletePartyRelationship,
} from '../api/queries';
import { formatDateTime } from '../utils/date';
import type {
  ReserveAdequacyResponse,
  ReserveHistoryEntry,
  ClaimParty,
  ClaimDocument,
  DocumentVersionGroup,
} from '../api/types';
import type { PatchClaimReserveBody } from '../api/client';

interface ReserveTabProps {
  reserveAmount: number | undefined;
  reserveHistory: ReserveHistoryEntry[];
  reserveHistoryLoading: boolean;
  reserveHistoryError: Error | null;
  reserveAdequacyData: ReserveAdequacyResponse | undefined;
  reserveAdequacyError: Error | null;
  patchReserveMutation: UseMutationResult<
    { claim_id: string; reserve_amount: number },
    Error,
    PatchClaimReserveBody
  >;
}

function ReserveTab({
  reserveAmount,
  reserveHistory,
  reserveHistoryLoading,
  reserveHistoryError,
  reserveAdequacyData,
  reserveAdequacyError,
  patchReserveMutation,
}: ReserveTabProps) {
  const [amount, setAmount] = useState('');
  const [reason, setReason] = useState('');
  const reserveError = reserveHistoryError ?? reserveAdequacyError;

  const handleAdjustReserve = (e: React.FormEvent) => {
    e.preventDefault();
    const num = parseFloat(amount);
    if (Number.isNaN(num) || num < 0) return;
    patchReserveMutation.mutate({ reserve_amount: num, reason: reason || undefined });
    setAmount('');
    setReason('');
  };

  return (
    <div className="space-y-6">
      {reserveError && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 flex items-start gap-3">
          <span className="text-lg">⚠️</span>
          <p className="text-sm text-red-400">
            {reserveError instanceof Error ? reserveError.message : 'Failed to load reserve data'}
          </p>
        </div>
      )}
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-4">Adjust Reserve</h3>
        <form onSubmit={handleAdjustReserve} className="space-y-3">
          <div>
            <label htmlFor="reserve-amount" className="block text-xs text-gray-500 mb-1">
              Amount ($) *
            </label>
            <input
              id="reserve-amount"
              type="number"
              min="0"
              step="0.01"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder={reserveAmount != null ? String(reserveAmount) : 'e.g. 5000'}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
              required
            />
          </div>
          <div>
            <label htmlFor="reserve-reason" className="block text-xs text-gray-500 mb-1">
              Reason (optional)
            </label>
            <input
              id="reserve-reason"
              type="text"
              maxLength={500}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. Supplemental estimate received"
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>
          {patchReserveMutation.isError && (
            <p className="text-sm text-red-400">
              {patchReserveMutation.error instanceof Error
                ? patchReserveMutation.error.message
                : 'Failed to update reserve'}
            </p>
          )}
          <button
            type="submit"
            disabled={patchReserveMutation.isPending}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-600 disabled:cursor-not-allowed rounded text-sm font-medium text-white transition-colors"
          >
            {patchReserveMutation.isPending ? 'Updating…' : 'Update Reserve'}
          </button>
        </form>
      </div>
      {reserveAdequacyData && (
        <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
          <h3 className="text-sm font-semibold text-gray-300 mb-4">Reserve Adequacy</h3>
          <div className="flex items-center gap-2 mb-2">
            <span
              className={`text-sm font-medium ${reserveAdequacyData.adequate ? 'text-emerald-400' : 'text-amber-400'}`}
            >
              {reserveAdequacyData.adequate ? '✓ Adequate' : '⚠ Needs attention'}
            </span>
          </div>
          {reserveAdequacyData.warnings.length > 0 && (
            <ul className="text-sm text-amber-400/90 space-y-1 mt-2">
              {reserveAdequacyData.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-4">Reserve History</h3>
        {reserveHistoryLoading ? (
          <div className="h-24 bg-gray-700/30 rounded skeleton-shimmer" />
        ) : reserveHistory.length === 0 ? (
          <EmptyState
            icon="💰"
            title="No reserve history"
            description="No reserve changes have been recorded for this claim."
          />
        ) : (
          <div className="space-y-3">
            {reserveHistory.map((entry) => (
              <div
                key={entry.id}
                className="rounded-lg bg-gray-900/50 p-3 ring-1 ring-gray-700/50"
              >
                <div className="flex items-center justify-between gap-2 mb-1">
                  <span className="text-xs font-medium text-blue-400">{entry.actor_id}</span>
                  <span className="text-xs text-gray-500">{formatDateTime(entry.created_at)}</span>
                </div>
                <p className="text-sm text-gray-300">
                  {entry.old_amount != null
                    ? `$${Number(entry.old_amount).toLocaleString()} → $${Number(entry.new_amount).toLocaleString()}`
                    : `Set to $${Number(entry.new_amount).toLocaleString()}`}
                </p>
                {entry.reason && (
                  <p className="text-xs text-gray-500 mt-1">{entry.reason}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Note Templates
// ---------------------------------------------------------------------------

const NOTE_TEMPLATES = [
  { label: 'Initial Contact', text: 'Initial contact attempted with claimant. Left voicemail / spoke with insured regarding claim details and next steps.' },
  { label: 'Inspection Scheduled', text: 'Vehicle inspection scheduled for [DATE] at [LOCATION]. Claimant has been notified.' },
  { label: 'Coverage Verified', text: 'Coverage verified for this loss. Policy is active with applicable coverage for the reported damages.' },
  { label: 'Claim Acknowledged', text: 'Claim receipt acknowledged per UCSPA requirements. Acknowledgment letter sent to claimant.' },
  { label: 'Awaiting Documents', text: 'Awaiting the following documents from claimant: [DOCUMENT LIST]. Follow-up scheduled for [DATE].' },
  { label: 'Estimate Received', text: 'Repair estimate received from [SHOP NAME]. Total estimate: $[AMOUNT]. Reviewing for authorization.' },
  { label: 'Payment Issued', text: 'Payment issued to [PAYEE] in the amount of $[AMOUNT] via [METHOD]. Check/reference #[NUMBER].' },
  { label: 'Supervisor Review', text: 'Claim reviewed with supervisor. Decision: [DECISION]. Notes: [NOTES].' },
];

interface NotesTabProps {
  notes: Array<{ id?: number; note: string; actor_id: string; created_at?: string }>;
  followUps: Array<{
    id: number;
    claim_id: string;
    user_type: string;
    message_content: string;
    status: string;
    response_content?: string;
    created_at?: string;
    responded_at?: string;
  }>;
  addNoteMutation: ReturnType<typeof useAddClaimNote>;
}

function NotesTab({ notes, followUps, addNoteMutation }: NotesTabProps) {
  const [noteText, setNoteText] = useState('');
  const [actorId, setActorId] = useState('adjuster');

  const handleAddNote = (e: React.FormEvent) => {
    e.preventDefault();
    if (!noteText.trim()) return;
    addNoteMutation.mutate(
      { note: noteText.trim(), actorId: actorId.trim() || 'adjuster' },
      { onSuccess: () => setNoteText('') }
    );
  };

  return (
    <div className="space-y-6">
      {/* Add note form */}
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-4">Add Note</h3>

        {/* Templates */}
        <div className="mb-3">
          <label className="block text-xs text-gray-500 mb-1">Quick Templates</label>
          <div className="flex flex-wrap gap-1.5">
            {NOTE_TEMPLATES.map((t) => (
              <button
                key={t.label}
                type="button"
                onClick={() => setNoteText(t.text)}
                className="px-2 py-1 text-xs bg-gray-900/50 text-gray-400 rounded ring-1 ring-gray-700/50 hover:bg-gray-800 hover:text-gray-200 transition-colors"
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        <form onSubmit={handleAddNote} className="space-y-3">
          <div>
            <label htmlFor="note-text" className="block text-xs text-gray-500 mb-1">Note *</label>
            <textarea
              id="note-text"
              value={noteText}
              onChange={(e) => setNoteText(e.target.value)}
              rows={4}
              required
              maxLength={5000}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500 resize-none"
              placeholder="Enter your note..."
            />
          </div>
          <div className="flex items-end gap-3">
            <div className="flex-1">
              <label htmlFor="note-actor" className="block text-xs text-gray-500 mb-1">Author</label>
              <input
                id="note-actor"
                type="text"
                value={actorId}
                onChange={(e) => setActorId(e.target.value)}
                maxLength={200}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
            <button
              type="submit"
              disabled={addNoteMutation.isPending || !noteText.trim()}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-600 disabled:cursor-not-allowed rounded text-sm font-medium text-white transition-colors"
            >
              {addNoteMutation.isPending ? 'Adding…' : 'Add Note'}
            </button>
          </div>
          {addNoteMutation.isError && (
            <p className="text-sm text-red-400">
              {addNoteMutation.error instanceof Error ? addNoteMutation.error.message : 'Failed to add note'}
            </p>
          )}
        </form>
      </div>

      {/* Existing notes */}
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-4">Claim Notes ({notes.length})</h3>
        {notes.length === 0 ? (
          <EmptyState icon="📝" title="No notes" description="No claim notes recorded yet." />
        ) : (
          <div className="space-y-3">
            {notes.map((n, i) => (
              <div key={n.id ?? i} className="rounded-lg bg-gray-900/50 p-3 ring-1 ring-gray-700/50">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-medium text-blue-400">{n.actor_id}</span>
                  {n.created_at && <span className="text-xs text-gray-500">{formatDateTime(n.created_at)}</span>}
                </div>
                <p className="text-sm text-gray-300 whitespace-pre-wrap">{n.note}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Follow-up messages */}
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-4">Follow-up Messages ({followUps.length})</h3>
        {followUps.length === 0 ? (
          <EmptyState icon="✉️" title="No follow-ups" description="No follow-up messages sent for this claim." />
        ) : (
          <div className="space-y-4">
            {followUps.map((msg) => (
              <div key={msg.id} className="rounded-lg bg-gray-900/50 p-4 ring-1 ring-gray-700/50">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xs font-medium text-amber-400 capitalize">{msg.user_type.replace(/_/g, ' ')}</span>
                  <span className={`text-xs px-2 py-0.5 rounded ${
                    msg.status === 'responded' ? 'bg-emerald-500/20 text-emerald-400'
                      : msg.status === 'sent' ? 'bg-blue-500/20 text-blue-400'
                        : 'bg-gray-500/20 text-gray-400'
                  }`}>{msg.status}</span>
                  {msg.created_at && <span className="text-xs text-gray-500">{formatDateTime(msg.created_at)}</span>}
                </div>
                <p className="text-sm text-gray-300 mb-2">{msg.message_content}</p>
                {msg.response_content && (
                  <div className="mt-2 pt-2 border-t border-gray-700/50">
                    <p className="text-xs text-gray-500 mb-1">Response</p>
                    <p className="text-sm text-gray-300 whitespace-pre-wrap">{msg.response_content}</p>
                    {msg.responded_at && <p className="text-xs text-gray-500 mt-1">{formatDateTime(msg.responded_at)}</p>}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Enhanced Documents Tab
// ---------------------------------------------------------------------------

const DOCUMENT_TYPES = [
  'police_report', 'estimate', 'medical_record', 'photo', 'pdf', 'other',
];

const REVIEW_STATUSES = ['pending', 'in_review', 'reviewed', 'rejected'];

const DOC_TYPE_ICONS: Record<string, string> = {
  police_report: '🚔', estimate: '📋', photo: '🖼️',
  medical_record: '🏥', pdf: '📄', other: '📎',
};

interface DocumentsTabProps {
  documents: ClaimDocument[];
  versionGroups?: DocumentVersionGroup[];
  versionGroupsTruncated?: boolean;
  attachments: Array<{ url: string; type: string; description?: string }>;
  docRequests: Array<{
    id: number; claim_id: string; document_type: string;
    requested_from?: string; status: string; received_at?: string; created_at?: string;
  }>;
  uploadMutation: ReturnType<typeof useUploadDocument>;
  updateDocMutation: ReturnType<typeof useUpdateDocument>;
  createDocRequestMutation: ReturnType<typeof useCreateDocumentRequest>;
}

function DocumentsTab({
  documents,
  versionGroups,
  versionGroupsTruncated,
  attachments,
  docRequests,
  uploadMutation,
  updateDocMutation,
  createDocRequestMutation,
}: DocumentsTabProps) {
  const [uploadType, setUploadType] = useState('other');
  const [uploadFrom, setUploadFrom] = useState('claimant');
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [reqDocType, setReqDocType] = useState('police_report');
  const [reqFrom, setReqFrom] = useState('');

  const handleFiles = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    for (const file of Array.from(files)) {
      uploadMutation.mutate({
        file,
        documentType: uploadType,
        receivedFrom: uploadFrom,
      });
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    handleFiles(e.dataTransfer.files);
  };

  const handleCreateRequest = (e: React.FormEvent) => {
    e.preventDefault();
    createDocRequestMutation.mutate({
      document_type: reqDocType,
      requested_from: reqFrom || undefined,
    });
  };

  // Determine if URL is an image
  const isImageUrl = (url?: string) => {
    if (!url) return false;
    const ext = url.split('.').pop()?.toLowerCase() ?? '';
    return ['jpg', 'jpeg', 'png', 'gif', 'webp', 'heic'].includes(ext);
  };

  return (
    <div className="space-y-6">
      {/* Upload */}
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-4">Upload Document</h3>
        <div className="grid grid-cols-2 gap-4 mb-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Document Type</label>
            <select
              value={uploadType}
              onChange={(e) => setUploadType(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              {DOCUMENT_TYPES.map((t) => (
                <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Received From</label>
            <input
              type="text"
              value={uploadFrom}
              onChange={(e) => setUploadFrom(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
              placeholder="claimant, repair_shop, etc."
            />
          </div>
        </div>
        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
            dragOver
              ? 'border-blue-500 bg-blue-500/10'
              : 'border-gray-700 hover:border-gray-600 hover:bg-gray-800/30'
          }`}
        >
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            accept=".pdf,.jpg,.jpeg,.png,.gif,.webp,.heic,.doc,.docx,.xls,.xlsx"
            onChange={(e) => handleFiles(e.target.files)}
          />
          <span className="text-3xl mb-2 block">📄</span>
          <p className="text-sm text-gray-400">
            {dragOver ? 'Drop files here' : 'Click or drag files to upload'}
          </p>
          <p className="text-xs text-gray-600 mt-1">
            PDF, images, Word, Excel — max 50 MB
          </p>
        </div>
        {uploadMutation.isPending && (
          <p className="text-xs text-blue-400 mt-2">Uploading…</p>
        )}
        {uploadMutation.isError && (
          <p className="text-xs text-red-400 mt-2">
            {uploadMutation.error instanceof Error ? uploadMutation.error.message : 'Upload failed'}
          </p>
        )}
      </div>

      {/* Version history (grouped by storage_key when API returns version_groups) */}
      {versionGroups && versionGroups.length > 0 && (
        <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
          <h3 className="text-sm font-semibold text-gray-300 mb-2">Version history</h3>
          <p className="text-xs text-gray-500 mb-4">
            Documents with the same storage key are shown as a timeline. The highest version is marked
            current; older rows are superseded.
          </p>
          {versionGroupsTruncated && (
            <p className="text-xs text-amber-400/90 mb-4">
              Version grouping used the first 500 matching documents only; totals may be incomplete for
              this claim.
            </p>
          )}
          <div className="space-y-4">
            {versionGroups.map((g) => (
              <div
                key={g.storage_key || `grp-${g.versions[0]?.id}`}
                className="rounded-lg bg-gray-900/40 ring-1 ring-gray-700/40 p-3"
              >
                <p className="text-xs text-gray-400 truncate font-mono" title={g.storage_key}>
                  {(g.storage_key || '').split('/').pop() || g.storage_key || '—'}
                </p>
                <div className="flex flex-wrap gap-2 mt-2">
                  {g.versions.map((v) => (
                    <div
                      key={v.id}
                      className={`rounded-md px-2 py-1 text-xs ${
                        v.is_current_version
                          ? 'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30'
                          : 'bg-gray-700/40 text-gray-400'
                      }`}
                    >
                      v{v.version ?? 1}
                      {v.is_current_version ? ' · current' : ' · superseded'}
                      <span className="text-gray-500 ml-1">#{v.id}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Documents list */}
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-4">
          Documents ({documents.length})
        </h3>
        {documents.length === 0 && attachments.length === 0 ? (
          <EmptyState icon="📎" title="No documents" description="No documents uploaded yet." />
        ) : (
          <div className="space-y-3">
            {documents.map((doc) => {
              const icon = DOC_TYPE_ICONS[doc.document_type] ?? '📎';
              const safeUrl = doc.url && (doc.url.startsWith('http') || doc.url.startsWith('/')) ? doc.url : '#';
              return (
                <div key={doc.id} className="rounded-lg bg-gray-900/50 p-3 ring-1 ring-gray-700/50">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-3 min-w-0">
                      <span className="text-lg shrink-0 mt-0.5">{icon}</span>
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-gray-200 truncate">
                          {doc.storage_key.split('/').pop() ?? `Document ${doc.id}`}
                        </p>
                        <div className="flex items-center gap-2 mt-1 flex-wrap">
                          <span className="text-xs text-gray-500 capitalize">{doc.document_type.replace(/_/g, ' ')}</span>
                          {doc.received_from && <span className="text-xs text-gray-600">from {doc.received_from}</span>}
                          <span className={`text-xs px-1.5 py-0.5 rounded ${
                            doc.review_status === 'approved' ? 'bg-emerald-500/20 text-emerald-400'
                              : doc.review_status === 'rejected' ? 'bg-red-500/20 text-red-400'
                                : 'bg-yellow-500/20 text-yellow-400'
                          }`}>
                            {doc.review_status}
                          </span>
                          {doc.privileged && <span className="text-xs bg-purple-500/20 text-purple-400 px-1.5 py-0.5 rounded">Privileged</span>}
                          <span className="text-xs bg-gray-700/60 text-gray-300 px-1.5 py-0.5 rounded">
                            v{doc.version ?? 1}
                          </span>
                          <span className="text-xs text-gray-600">{formatDateTime(doc.created_at)}</span>
                        </div>
                        {/* Preview for images */}
                        {isImageUrl(doc.url) && doc.url && (
                          <div className="mt-2">
                            <img src={safeUrl} alt="" className="max-w-xs max-h-32 rounded border border-gray-700/50 object-cover" />
                          </div>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <select
                        value={doc.review_status}
                        onChange={(e) => updateDocMutation.mutate({ docId: doc.id, body: { review_status: e.target.value } })}
                        className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-gray-300 focus:outline-none focus:ring-1 focus:ring-blue-500"
                      >
                        {REVIEW_STATUSES.map((s) => (
                          <option key={s} value={s}>{s}</option>
                        ))}
                      </select>
                      <a href={safeUrl} target="_blank" rel="noopener noreferrer" className="text-sm text-blue-400 hover:text-blue-300">
                        View →
                      </a>
                    </div>
                  </div>
                </div>
              );
            })}
            {/* Legacy attachments not yet in documents table */}
            {attachments.map((att, i) => {
              const icon = DOC_TYPE_ICONS[att.type] ?? '📎';
              const filename = att.url.split('/').pop() ?? `Document ${i + 1}`;
              const safeHref = att.url.startsWith('http') || att.url.startsWith('/') ? att.url : '#';
              return (
                <div key={`att-${i}`} className="flex items-center justify-between gap-4 rounded-lg bg-gray-900/50 p-3 ring-1 ring-gray-700/50">
                  <div className="flex items-center gap-3 min-w-0">
                    <span className="text-lg shrink-0">{icon}</span>
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-200 truncate">{att.description ?? filename}</p>
                      <p className="text-xs text-gray-500 capitalize">{att.type || 'Document'}</p>
                    </div>
                  </div>
                  <a href={safeHref} target="_blank" rel="noopener noreferrer" className="text-sm text-blue-400 hover:text-blue-300">View →</a>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <DocumentVersionCompare documents={documents} />

      {/* Document Requests */}
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-4">Document Requests ({docRequests.length})</h3>
        <form onSubmit={handleCreateRequest} className="flex items-end gap-3 mb-4">
          <div className="flex-1">
            <label className="block text-xs text-gray-500 mb-1">Document Type</label>
            <select
              value={reqDocType}
              onChange={(e) => setReqDocType(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              {DOCUMENT_TYPES.map((t) => (
                <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>
              ))}
            </select>
          </div>
          <div className="flex-1">
            <label className="block text-xs text-gray-500 mb-1">Request From</label>
            <input
              type="text"
              value={reqFrom}
              onChange={(e) => setReqFrom(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
              placeholder="e.g. claimant, police dept"
            />
          </div>
          <button
            type="submit"
            disabled={createDocRequestMutation.isPending}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-600 disabled:cursor-not-allowed rounded text-sm font-medium text-white transition-colors"
          >
            Request
          </button>
        </form>
        {docRequests.length === 0 ? (
          <p className="text-sm text-gray-500">No document requests.</p>
        ) : (
          <div className="space-y-2">
            {docRequests.map((req) => (
              <div key={req.id} className="flex items-center justify-between gap-3 rounded-lg bg-gray-900/50 p-3 ring-1 ring-gray-700/50">
                <div>
                  <p className="text-sm text-gray-200 capitalize">{req.document_type.replace(/_/g, ' ')}</p>
                  <p className="text-xs text-gray-500">
                    {req.requested_from && `From: ${req.requested_from} · `}
                    {formatDateTime(req.created_at)}
                  </p>
                </div>
                <span className={`text-xs px-2 py-0.5 rounded ${
                  req.status === 'received' ? 'bg-emerald-500/20 text-emerald-400'
                    : req.status === 'requested' ? 'bg-blue-500/20 text-blue-400'
                      : req.status === 'partial' ? 'bg-yellow-500/20 text-yellow-400'
                        : req.status === 'overdue' ? 'bg-red-500/20 text-red-400'
                          : 'bg-gray-500/20 text-gray-400'
                }`}>
                  {req.status}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

const RELATIONSHIP_TYPES = ['represented_by', 'lienholder_for', 'witness_for'];

interface AddRelationshipFormProps {
  parties: ClaimParty[];
  onSubmit: (body: { from_party_id: number; to_party_id: number; relationship_type: string }) => void;
  isPending: boolean;
  error: Error | null;
  onSuccess: () => void;
}

function AddRelationshipForm({ parties, onSubmit, isPending, error, onSuccess }: AddRelationshipFormProps) {
  const [fromId, setFromId] = useState('');
  const [toId, setToId] = useState('');
  const [relType, setRelType] = useState(RELATIONSHIP_TYPES[0]);
  const [prevPending, setPrevPending] = useState(isPending);

  useEffect(() => {
    if (prevPending && !isPending && !error) {
      setFromId('');
      setToId('');
      setRelType(RELATIONSHIP_TYPES[0]);
      onSuccess();
    }
    setPrevPending(isPending);
  }, [isPending, prevPending, error, onSuccess]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!fromId || !toId || fromId === toId) return;
    onSubmit({
      from_party_id: Number(fromId),
      to_party_id: Number(toId),
      relationship_type: relType,
    });
  };

  const partyLabel = (p: ClaimParty) =>
    `${p.name ?? `#${p.id}`} (${p.party_type.replace(/_/g, ' ')})`;

  if (parties.length < 2) return null;

  return (
    <form onSubmit={handleSubmit} className="mt-4 pt-4 border-t border-gray-700/50 space-y-3">
      <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
        Add Relationship
      </h4>
      {error && (
        <p className="text-xs text-red-400">
          {error.message}
        </p>
      )}
      <div className="flex flex-wrap gap-3 items-end">
        <div className="flex-1 min-w-[140px]">
          <label htmlFor="rel-from" className="block text-xs text-gray-500 mb-1">From</label>
          <select
            id="rel-from"
            value={fromId}
            onChange={(e) => {
              const newFromId = e.target.value;
              setFromId(newFromId);
              if (newFromId === toId) {
                setToId('');
              }
            }}
            required
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            <option value="">Select party…</option>
            {parties.map((p) => (
              <option key={p.id} value={p.id}>{partyLabel(p)}</option>
            ))}
          </select>
        </div>
        <div className="flex-1 min-w-[140px]">
          <label htmlFor="rel-type" className="block text-xs text-gray-500 mb-1">Type</label>
          <select
            id="rel-type"
            value={relType}
            onChange={(e) => setRelType(e.target.value)}
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            {RELATIONSHIP_TYPES.map((t) => (
              <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>
            ))}
          </select>
        </div>
        <div className="flex-1 min-w-[140px]">
          <label htmlFor="rel-to" className="block text-xs text-gray-500 mb-1">To</label>
          <select
            id="rel-to"
            value={toId}
            onChange={(e) => setToId(e.target.value)}
            required
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            <option value="">Select party…</option>
            {parties.filter((p) => String(p.id) !== fromId).map((p) => (
              <option key={p.id} value={p.id}>{partyLabel(p)}</option>
            ))}
          </select>
        </div>
        <button
          type="submit"
          disabled={isPending || !fromId || !toId}
          className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-500 text-sm text-white disabled:opacity-50 transition-colors"
        >
          {isPending ? 'Adding…' : 'Add'}
        </button>
      </div>
    </form>
  );
}

export default function ClaimDetail() {
  const { claimId } = useParams<{ claimId: string }>();
  const [activeTab, setActiveTab] = useState('overview');
  const { data: claim, isLoading: claimLoading, error: claimError } = useClaim(claimId);
  const {
    data: historyData,
    isLoading: historyLoading,
    error: historyError,
  } = useClaimHistory(claimId);
  const {
    data: workflowsData,
    isLoading: workflowsLoading,
    error: workflowsError,
  } = useClaimWorkflows(claimId);
  const {
    data: reserveHistoryData,
    isLoading: reserveHistoryLoading,
    error: reserveHistoryError,
  } = useClaimReserveHistory(claimId);
  const {
    data: reserveAdequacyData,
    error: reserveAdequacyError,
  } = useClaimReserveAdequacy(claimId);
  const patchReserveMutation = usePatchClaimReserve(claimId);
  const addNoteMutation = useAddClaimNote(claimId);
  const { data: docsData } = useClaimDocuments(claimId, { groupBy: 'storage_key' });
  const uploadDocMutation = useUploadDocument(claimId);
  const updateDocMutation = useUpdateDocument(claimId);
  const { data: docRequestsData } = useDocumentRequests(claimId);
  const createDocRequestMutation = useCreateDocumentRequest(claimId);
  const createRelMutation = useCreatePartyRelationship(claimId);
  const deleteRelMutation = useDeletePartyRelationship(claimId);
  const history = historyData?.history ?? [];
  const workflows = workflowsData?.workflows ?? [];
  const notes = claim?.notes ?? [];
  const followUps = claim?.follow_up_messages ?? [];
  const parties = claim?.parties ?? [];
  const tasks = claim?.tasks ?? [];
  const attachments = claim?.attachments ?? [];
  const subrogationCases = claim?.subrogation_cases ?? [];
  const documents = docsData?.documents ?? [];
  const docRequests = docRequestsData?.requests ?? [];
  const notesFollowUpsCount = notes.length + followUps.length;
  const reserveHistory = reserveHistoryData?.history ?? [];
  const loading = claimLoading || historyLoading || workflowsLoading;
  const error = claimError ?? historyError ?? workflowsError;

  if (loading) {
    return (
      <div className="space-y-4 animate-fade-in">
        <div className="h-8 bg-gray-700/50 rounded w-48 skeleton-shimmer" />
        <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6 space-y-4">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-6 bg-gray-700/30 rounded w-full skeleton-shimmer" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4 animate-fade-in">
        <PageHeader title="Claim" backTo="/claims" backLabel="Claims" />
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 flex items-start gap-3">
          <span className="text-lg">⚠️</span>
          <p className="text-sm text-red-400">{error instanceof Error ? error.message : 'Unknown error'}</p>
        </div>
      </div>
    );
  }

  if (!claim) return null;

  const tabs = [
    { key: 'overview', label: 'Overview', icon: '📋' },
    { key: 'tasks', label: `Tasks (${claim?.tasks_total ?? tasks.length})`, icon: '☑️' },
    { key: 'documents', label: `Documents (${documents.length || attachments.length})`, icon: '📎' },
    { key: 'reserve', label: `Reserve (${reserveHistory.length})`, icon: '💰' },
    { key: 'payments', label: 'Payments', icon: '💳' },
    { key: 'notes', label: `Notes (${notesFollowUpsCount})`, icon: '📝' },
    { key: 'comms', label: 'Comms Log', icon: '💬' },
    { key: 'coverage', label: 'Coverage', icon: '🛡️' },
    { key: 'audit', label: `Audit (${history.length})`, icon: '📜' },
    { key: 'workflows', label: `Workflows (${workflows.length})`, icon: '🔄' },
  ];

  const fields = [
    { label: 'Policy Number', value: claim.policy_number },
    { label: 'VIN', value: claim.vin },
    { label: 'Vehicle', value: `${claim.vehicle_year ?? ''} ${claim.vehicle_make ?? ''} ${claim.vehicle_model ?? ''}`.trim() || '—' },
    { label: 'Incident Date', value: claim.incident_date },
    { label: 'Estimated Damage', value: claim.estimated_damage != null ? `$${Number(claim.estimated_damage).toLocaleString()}` : '—', isMoney: true },
    { label: 'Reserve Amount', value: claim.reserve_amount != null ? `$${Number(claim.reserve_amount).toLocaleString()}` : '—', isMoney: true },
    { label: 'Payout Amount', value: claim.payout_amount != null ? `$${Number(claim.payout_amount).toLocaleString()}` : '—', isMoney: true, isPayout: claim.payout_amount != null },
    ...((claim.liability_percentage != null || claim.liability_basis) ? [
      { label: 'Liability %', value: claim.liability_percentage != null ? `${claim.liability_percentage}%` : '—' },
      { label: 'Liability Basis', value: claim.liability_basis ?? '—' },
    ] : []),
    { label: 'Created', value: formatDateTime(claim.created_at) ?? '—' },
    { label: 'Updated', value: formatDateTime(claim.updated_at) ?? '—' },
  ];

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <PageHeader
        title={claim.id}
        backTo="/claims"
        backLabel="Claims"
        actions={
          <div className="flex items-center gap-3">
            <TypeBadge type={claim.claim_type} />
            <StatusBadge status={claim.status} />
          </div>
        }
      />

      {/* Tabs */}
      <div className="border-b border-gray-700/50">
        <nav className="flex gap-1">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-2 px-4 pb-3 pt-1 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.key
                  ? 'border-blue-500 text-blue-400'
                  : 'border-transparent text-gray-500 hover:text-gray-300 hover:border-gray-600'
              }`}
            >
              <span className="text-sm">{tab.icon}</span>
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab content */}
      <div className="animate-fade-in" key={activeTab}>
        {activeTab === 'overview' && (
          <div className="space-y-6">
            {/* Details grid */}
            <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
              <h3 className="text-sm font-semibold text-gray-300 mb-4">Claim Details</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {fields.map((f) => (
                  <div key={f.label}>
                    <p className="text-xs text-gray-500 uppercase tracking-wider">{f.label}</p>
                    <p className={`text-sm mt-0.5 font-mono ${
                      f.isPayout ? 'text-emerald-400 font-semibold' : f.isMoney ? 'text-gray-200' : 'text-gray-300'
                    }`}>
                      {f.value ?? '—'}
                    </p>
                  </div>
                ))}
              </div>
            </div>

            {/* Parties */}
            {parties.length > 0 && (
              <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
                <h3 className="text-sm font-semibold text-gray-300 mb-4">Parties</h3>
                <div className="space-y-4">
                  {parties.map((p) => (
                    <div
                      key={p.id}
                      className="flex flex-wrap gap-x-6 gap-y-1 text-sm border-b border-gray-700/50 pb-3 last:border-0 last:pb-0"
                    >
                      <span className="font-medium text-gray-200 capitalize">
                        {p.party_type.replace(/_/g, ' ')}
                      </span>
                      {p.name && <span className="text-gray-400">{p.name}</span>}
                      {p.role && (
                        <span className="text-gray-500 text-xs">({p.role})</span>
                      )}
                      {p.email && (
                        <a
                          href={`mailto:${p.email}`}
                          className="text-blue-400 hover:underline"
                        >
                          {p.email}
                        </a>
                      )}
                      {p.phone && (
                        <a
                          href={`tel:${p.phone}`}
                          className="text-blue-400 hover:underline"
                        >
                          {p.phone}
                        </a>
                      )}
                      {(p.consent_status || p.authorization_status) && (
                        <span className="text-gray-500 text-xs">
                          Consent: {p.consent_status ?? '—'} · Auth: {p.authorization_status ?? '—'}
                        </span>
                      )}
                      {p.relationships && p.relationships.length > 0 && (
                        <div className="w-full basis-full mt-1 space-y-1">
                          {p.relationships.map((r) => {
                            const target = parties.find((x) => x.id === r.to_party_id);
                            const label = target?.name ?? `#${r.to_party_id}`;
                            return (
                              <span
                                key={r.id}
                                className="inline-flex items-center gap-1 text-gray-500 text-xs mr-3"
                              >
                                {r.relationship_type.replace(/_/g, ' ')} → {label}
                                <button
                                  type="button"
                                  title="Remove relationship"
                                  onClick={() => deleteRelMutation.mutate(r.id)}
                                  className="ml-1 text-red-400/60 hover:text-red-400 transition-colors"
                                >
                                  ✕
                                </button>
                              </span>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
                <AddRelationshipForm
                  parties={parties}
                  onSubmit={(body) => createRelMutation.mutate(body)}
                  isPending={createRelMutation.isPending}
                  error={createRelMutation.error}
                  onSuccess={() => {}}
                />
              </div>
            )}

            {/* Subrogation cases */}
            {subrogationCases.length > 0 && (
              <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
                <h3 className="text-sm font-semibold text-gray-300 mb-4">Subrogation Cases</h3>
                <div className="space-y-4">
                  {subrogationCases.map((sc) => (
                    <div
                      key={sc.id}
                      className="rounded-lg bg-gray-900/50 p-4 ring-1 ring-gray-700/50"
                    >
                      <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
                        <span className="font-medium text-gray-200">{sc.case_id}</span>
                        <span className="text-gray-400">
                          ${Number(sc.amount_sought).toLocaleString()} sought
                        </span>
                        {sc.opposing_carrier && (
                          <span className="text-gray-500">vs {sc.opposing_carrier}</span>
                        )}
                        <span
                          className={`text-xs px-2 py-0.5 rounded ${
                            sc.arbitration_status === 'filed'
                              ? 'bg-amber-500/20 text-amber-400'
                              : sc.status === 'full'
                                ? 'bg-emerald-500/20 text-emerald-400'
                                : sc.status === 'partial'
                                  ? 'bg-amber-500/20 text-amber-400'
                                  : sc.status === 'closed_no_recovery'
                                    ? 'bg-gray-500/20 text-gray-500'
                                    : sc.status === 'pending'
                                      ? 'bg-blue-500/20 text-blue-400'
                                      : 'bg-gray-500/20 text-gray-400'
                          }`}
                        >
                          {sc.arbitration_status === 'filed'
                            ? `Arbitration: ${sc.arbitration_forum ?? 'filed'}`
                            : sc.status.replace(/_/g, ' ')}
                        </span>
                      </div>
                      {(sc.liability_percentage != null || sc.liability_basis || sc.recovery_amount != null) && (
                        <p className="text-xs text-gray-500 mt-2">
                          {sc.liability_percentage != null && `Liability: ${sc.liability_percentage}%`}
                          {sc.liability_percentage != null && sc.liability_basis && ' · '}
                          {sc.liability_basis}
                          {sc.recovery_amount != null && (
                            <span>
                              {sc.liability_percentage != null || sc.liability_basis ? ' · ' : ''}
                              Recovered: ${Number(sc.recovery_amount).toLocaleString()}
                            </span>
                          )}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Descriptions */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6 border-l-[3px] border-l-blue-500/50">
                <h3 className="text-sm font-semibold text-gray-300 mb-2">Incident Description</h3>
                <p className="text-sm text-gray-400 leading-relaxed">
                  {claim.incident_description ?? 'No description provided.'}
                </p>
              </div>
              <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6 border-l-[3px] border-l-amber-500/50">
                <h3 className="text-sm font-semibold text-gray-300 mb-2">Damage Description</h3>
                <p className="text-sm text-gray-400 leading-relaxed">
                  {claim.damage_description ?? 'No description provided.'}
                </p>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'tasks' && (
          <TaskPanel claimId={claim.id} tasks={tasks} />
        )}
        {activeTab === 'reserve' && (
          <ReserveTab
            reserveAmount={claim.reserve_amount}
            reserveHistory={reserveHistory}
            reserveHistoryLoading={reserveHistoryLoading}
            reserveHistoryError={reserveHistoryError}
            reserveAdequacyData={reserveAdequacyData}
            reserveAdequacyError={reserveAdequacyError}
            patchReserveMutation={patchReserveMutation}
          />
        )}
        {activeTab === 'documents' && (
          <DocumentsTab
            documents={documents}
            versionGroups={docsData?.version_groups}
            versionGroupsTruncated={docsData?.version_groups_truncated}
            attachments={attachments}
            docRequests={docRequests}
            uploadMutation={uploadDocMutation}
            updateDocMutation={updateDocMutation}
            createDocRequestMutation={createDocRequestMutation}
          />
        )}

        {activeTab === 'notes' && (
          <NotesTab
            notes={notes}
            followUps={followUps}
            addNoteMutation={addNoteMutation}
          />
        )}

        {activeTab === 'payments' && (
          <PaymentPanel claimId={claim.id} />
        )}

        {activeTab === 'comms' && (
          <CommunicationLog
            notes={notes}
            followUps={followUps}
            auditEvents={history}
          />
        )}

        {activeTab === 'coverage' && (
          <CoverageSummary
            policyNumber={claim.policy_number}
            vin={claim.vin}
            claimType={claim.claim_type}
          />
        )}

        {activeTab === 'audit' && (
          <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
            <h3 className="text-sm font-semibold text-gray-300 mb-4">Audit History</h3>
            <AuditTimeline events={history} />
          </div>
        )}

        {activeTab === 'workflows' && (
          <div className="space-y-4">
            {workflows.length === 0 ? (
              <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
                <EmptyState
                  icon="🔄"
                  title="No workflow runs"
                  description="No workflow runs recorded for this claim."
                />
              </div>
            ) : (
              workflows.map((wf, i) => (
                <div key={wf.id ?? i} className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
                  <div className="flex items-center gap-3 mb-4">
                    <h3 className="text-sm font-semibold text-gray-300">
                      Run #{wf.id}
                    </h3>
                    <TypeBadge type={wf.claim_type} />
                    <span className="text-xs text-gray-500">
                      {formatDateTime(wf.created_at) ?? ''}
                    </span>
                  </div>

                  <div className="space-y-4">
                    <div>
                      <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Router Output</p>
                      <div className="bg-gray-900 rounded-lg p-3 ring-1 ring-gray-700/50">
                        <StructuredOutputDisplay value={wf.router_output ?? ''} />
                      </div>
                    </div>
                    <div>
                      <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Workflow Output</p>
                      <div className="bg-gray-900 rounded-lg p-3 max-h-96 overflow-y-auto ring-1 ring-gray-700/50">
                        <StructuredOutputDisplay value={wf.workflow_output ?? ''} />
                      </div>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}
