import { useState, useCallback, useRef, useEffect } from 'react';
import { Link } from 'react-router-dom';
import StatusBadge from '../components/StatusBadge';
import {
  processClaimAsync,
  streamClaimUpdates,
  type ProcessClaimPayload,
  type ClaimStreamUpdate,
} from '../api/client';
import type { Claim, AuditEvent, WorkflowRun } from '../api/types';

/** Form state allows vehicle_year to be undefined when cleared (for validation). */
type ClaimFormState = Omit<ProcessClaimPayload, 'vehicle_year'> & {
  vehicle_year?: number;
};

const INITIAL_FORM: ClaimFormState = {
  policy_number: '',
  vin: '',
  vehicle_year: new Date().getFullYear(),
  vehicle_make: '',
  vehicle_model: '',
  incident_date: new Date().toISOString().slice(0, 10),
  incident_description: '',
  damage_description: '',
  estimated_damage: undefined,
};

export default function NewClaimForm() {
  const [form, setForm] = useState<ClaimFormState>(INITIAL_FORM);
  const [files, setFiles] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [claimId, setClaimId] = useState<string | null>(null);
  const [claim, setClaim] = useState<Claim | null>(null);
  const [history, setHistory] = useState<AuditEvent[]>([]);
  const [workflows, setWorkflows] = useState<WorkflowRun[]>([]);
  const [done, setDone] = useState(false);
  const abortStreamRef = useRef<(() => void) | null>(null);

  const updateField = useCallback(
    <K extends keyof ClaimFormState>(key: K, value: ClaimFormState[K]) => {
      setForm((prev) => ({ ...prev, [key]: value }));
    },
    []
  );

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    setClaimId(null);
    setClaim(null);
    setHistory([]);
    setWorkflows([]);
    setDone(false);

    if (abortStreamRef.current) {
      abortStreamRef.current();
      abortStreamRef.current = null;
    }

    try {
      const payload: ProcessClaimPayload = {
        ...form,
        vehicle_year: form.vehicle_year ?? new Date().getFullYear(),
      };
      const { claim_id } = await processClaimAsync(payload, files.length ? files : undefined);
      setClaimId(claim_id);

      const abort = streamClaimUpdates(
        claim_id,
        (data: ClaimStreamUpdate) => {
          if (data.error) {
            setError(data.error);
            setDone(true);
            return;
          }
          if (data.claim) setClaim(data.claim);
          if (data.history) setHistory(data.history);
          if (data.workflows) setWorkflows(data.workflows);
          if (data.done) setDone(true);
        },
        (err) => {
          setError(err.message);
          setDone(true);
        }
      );
      abortStreamRef.current = abort;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to submit claim');
      setDone(true);
    } finally {
      setSubmitting(false);
    }
  };

  const resetForm = () => {
    if (abortStreamRef.current) {
      abortStreamRef.current();
      abortStreamRef.current = null;
    }
    setForm(INITIAL_FORM);
    setFiles([]);
    setClaimId(null);
    setClaim(null);
    setHistory([]);
    setWorkflows([]);
    setDone(false);
    setError(null);
  };

  useEffect(() => {
    return () => {
      if (abortStreamRef.current) {
        abortStreamRef.current();
      }
    };
  }, []);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">New Claim</h1>
        <p className="text-sm text-gray-500 mt-1">
          Submit a claim and watch it get routed and resolved in realtime
        </p>
      </div>

      <form onSubmit={handleSubmit} className="bg-white rounded-xl border border-gray-200 p-6 space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <label htmlFor="policy_number" className="block text-sm font-medium text-gray-700 mb-1">
              Policy Number
            </label>
            <input
              id="policy_number"
              type="text"
              value={form.policy_number}
              onChange={(e) => updateField('policy_number', e.target.value)}
              required
              className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="POL-001"
            />
          </div>
          <div>
            <label htmlFor="vin" className="block text-sm font-medium text-gray-700 mb-1">
              VIN
            </label>
            <input
              id="vin"
              type="text"
              value={form.vin}
              onChange={(e) => updateField('vin', e.target.value)}
              required
              className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="1HGBH41JXMN109186"
            />
          </div>
          <div>
            <label htmlFor="vehicle_year" className="block text-sm font-medium text-gray-700 mb-1">
              Vehicle Year
            </label>
            <input
              id="vehicle_year"
              type="number"
              value={form.vehicle_year ?? ''}
              onChange={(e) => {
                const raw = e.target.value;
                const num = parseInt(raw, 10);
                updateField(
                  'vehicle_year',
                  raw === '' ? undefined : (Number.isNaN(num) ? form.vehicle_year : num)
                );
              }}
              required
              min={1900}
              max={2100}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label htmlFor="vehicle_make" className="block text-sm font-medium text-gray-700 mb-1">
              Vehicle Make
            </label>
            <input
              id="vehicle_make"
              type="text"
              value={form.vehicle_make}
              onChange={(e) => updateField('vehicle_make', e.target.value)}
              required
              className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Honda"
            />
          </div>
          <div>
            <label htmlFor="vehicle_model" className="block text-sm font-medium text-gray-700 mb-1">
              Vehicle Model
            </label>
            <input
              id="vehicle_model"
              type="text"
              value={form.vehicle_model}
              onChange={(e) => updateField('vehicle_model', e.target.value)}
              required
              className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Accord"
            />
          </div>
          <div>
            <label htmlFor="incident_date" className="block text-sm font-medium text-gray-700 mb-1">
              Incident Date
            </label>
            <input
              id="incident_date"
              type="date"
              value={form.incident_date}
              onChange={(e) => updateField('incident_date', e.target.value)}
              required
              className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label htmlFor="estimated_damage" className="block text-sm font-medium text-gray-700 mb-1">
              Estimated Damage ($)
            </label>
            <input
              id="estimated_damage"
              type="number"
              value={form.estimated_damage ?? ''}
              onChange={(e) =>
                updateField(
                  'estimated_damage',
                  e.target.value ? parseFloat(e.target.value) : undefined
                )
              }
              min={0}
              step={0.01}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Optional"
            />
          </div>
        </div>

        <div>
          <label htmlFor="incident_description" className="block text-sm font-medium text-gray-700 mb-1">
            Incident Description
          </label>
          <textarea
            id="incident_description"
            value={form.incident_description}
            onChange={(e) => updateField('incident_description', e.target.value)}
            required
            rows={3}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Describe what happened..."
          />
        </div>

        <div>
          <label htmlFor="damage_description" className="block text-sm font-medium text-gray-700 mb-1">
            Damage Description
          </label>
          <textarea
            id="damage_description"
            value={form.damage_description}
            onChange={(e) => updateField('damage_description', e.target.value)}
            required
            rows={3}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="Describe the vehicle damage..."
          />
        </div>

        <div>
          <label htmlFor="attachments" className="block text-sm font-medium text-gray-700 mb-1">
            Attachments (optional)
          </label>
          <input
            id="attachments"
            type="file"
            multiple
            accept="image/*,.pdf"
            onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
            className="w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-medium file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
          />
          {files.length > 0 && (
            <p className="mt-1 text-xs text-gray-500">{files.length} file(s) selected</p>
          )}
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4">
            <p className="text-red-800">{error}</p>
          </div>
        )}

        <div className="flex gap-3">
          <button
            type="submit"
            disabled={submitting || (!!claimId && !done)}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {submitting ? 'Submitting...' : claimId && !done ? 'Processing...' : 'Submit Claim'}
          </button>
          {claimId && done && (
            <>
              <Link
                to={`/claims/${claimId}`}
                className="px-4 py-2 bg-green-600 text-white rounded-lg font-medium hover:bg-green-700"
              >
                View Claim
              </Link>
              <button
                type="button"
                onClick={resetForm}
                className="px-4 py-2 border border-gray-300 rounded-lg font-medium hover:bg-gray-50"
              >
                New Claim
              </button>
            </>
          )}
        </div>
      </form>

      {/* Realtime processing view */}
      {claimId && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-100 bg-gray-50">
            <h2 className="text-lg font-semibold text-gray-900">Processing in Realtime</h2>
            <p className="text-sm text-gray-500 mt-0.5">
              Claim {claimId} — routing and resolution updates stream live below
            </p>
          </div>

          <div className="p-6 space-y-6">
            {/* Status and routing */}
            <div className="flex flex-wrap items-center gap-4">
              <div>
                <span className="text-sm text-gray-500 mr-2">Status:</span>
                <StatusBadge status={claim?.status ?? 'pending'} />
              </div>
              {claim?.claim_type && (
                <div>
                  <span className="text-sm text-gray-500 mr-2">Routed to:</span>
                  <span className="font-medium text-gray-900">
                    {claim.claim_type.replace(/_/g, ' ')}
                  </span>
                </div>
              )}
              {!done && (
                <span className="inline-flex items-center gap-1.5 text-sm text-blue-600">
                  <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
                  Live
                </span>
              )}
            </div>

            {/* Audit timeline */}
            {history.length > 0 && (
              <div>
                <h3 className="text-sm font-medium text-gray-700 mb-2">Audit Log</h3>
                <ul className="space-y-2">
                  {history.map((evt, i) => (
                    <li
                      key={evt.id ?? i}
                      className="flex items-start gap-2 text-sm py-2 px-3 bg-gray-50 rounded-lg"
                    >
                      <span className="text-gray-500 shrink-0">
                        {evt.created_at
                          ? new Date(evt.created_at).toLocaleTimeString()
                          : '—'}
                      </span>
                      <span className="font-medium">{evt.action}</span>
                      {evt.old_status && evt.new_status && (
                        <span className="text-gray-500">
                          {evt.old_status} → {evt.new_status}
                        </span>
                      )}
                      {evt.details && (
                        <span className="text-gray-600 truncate">{evt.details}</span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Workflow runs */}
            {workflows.length > 0 && (
              <div>
                <h3 className="text-sm font-medium text-gray-700 mb-2">Workflow Runs</h3>
                <div className="space-y-3">
                  {workflows.map((wf, i) => (
                    <div
                      key={wf.id ?? i}
                      className="p-4 border border-gray-200 rounded-lg bg-white"
                    >
                      <div className="flex items-center gap-2 mb-2">
                        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-indigo-100 text-indigo-800">
                          {wf.claim_type?.replace(/_/g, ' ') ?? 'unclassified'}
                        </span>
                        {wf.created_at && (
                          <span className="text-xs text-gray-500">
                            {new Date(wf.created_at).toLocaleString()}
                          </span>
                        )}
                      </div>
                      {wf.router_output && (
                        <p className="text-sm text-gray-600 mb-1">
                          <span className="font-medium">Router:</span> {wf.router_output}
                        </p>
                      )}
                      {wf.workflow_output && (
                        <p className="text-sm text-gray-600">
                          <span className="font-medium">Output:</span> {wf.workflow_output}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {!claim && !done && !error && (
              <p className="text-sm text-gray-500">Waiting for first update...</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
