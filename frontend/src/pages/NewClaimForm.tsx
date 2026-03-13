import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { Link } from 'react-router-dom';
import PageHeader from '../components/PageHeader';
import PolicySelect from '../components/PolicySelect';
import StatusBadge from '../components/StatusBadge';
import TypeBadge from '../components/TypeBadge';
import StructuredOutputDisplay from '../components/StructuredOutputDisplay';
import {
  processClaimAsync,
  streamClaimUpdates,
  type ProcessClaimPayload,
  type ClaimStreamUpdate,
} from '../api/client';
import type { Claim, AuditEvent, WorkflowRun } from '../api/types';
import { usePolicies } from '../api/queries';

type VehicleRecord = {
  policy_number: string;
  vin: string;
  vehicle_year: number;
  vehicle_make: string;
  vehicle_model: string;
};

/** Form state allows vehicle_year to be undefined when cleared (for validation). */
type ClaimFormState = Omit<ProcessClaimPayload, 'vehicle_year'> & {
  vehicle_year?: number;
};

const INITIAL_FORM: ClaimFormState = {
  policy_number: '',
  vin: '',
  vehicle_year: undefined,
  vehicle_make: '',
  vehicle_model: '',
  incident_date: new Date().toISOString().slice(0, 10),
  incident_description: '',
  damage_description: '',
  estimated_damage: undefined,
};

const inputClasses =
  'w-full border border-gray-700 rounded-lg px-3 py-2 bg-gray-800 text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/40 transition-colors';

const labelClasses = 'block text-sm font-medium text-gray-300 mb-1.5';

const selectClasses =
  'w-full border border-gray-700 rounded-lg px-3 py-2 bg-gray-800 text-gray-200 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500/40 transition-colors';

export default function NewClaimForm() {
  const { data: policiesData } = usePolicies();
  const policies = policiesData?.policies ?? [];
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

  const allVehicles: VehicleRecord[] = useMemo(
    () =>
      policies.flatMap((p) =>
        p.vehicles.map((v) => ({
          ...v,
          policy_number: p.policy_number,
        }))
      ),
    [policies]
  );

  const filterByOther = useCallback(
    (excludeField: keyof Pick<ClaimFormState, 'policy_number' | 'vin' | 'vehicle_year' | 'vehicle_make' | 'vehicle_model'>) => {
      return allVehicles.filter((v) => {
        if (excludeField !== 'policy_number' && form.policy_number && v.policy_number !== form.policy_number)
          return false;
        if (excludeField !== 'vehicle_year' && form.vehicle_year != null && v.vehicle_year !== form.vehicle_year)
          return false;
        if (excludeField !== 'vehicle_make' && form.vehicle_make && v.vehicle_make !== form.vehicle_make)
          return false;
        if (excludeField !== 'vehicle_model' && form.vehicle_model && v.vehicle_model !== form.vehicle_model)
          return false;
        if (excludeField !== 'vin' && form.vin && v.vin !== form.vin) return false;
        return true;
      });
    },
    [allVehicles, form]
  );

  const policyOptions = useMemo(
    () => [...new Set(allVehicles.map((v) => v.policy_number))].sort(),
    [allVehicles]
  );

  const yearOptions = useMemo(() => {
    let matches = allVehicles;
    if (form.policy_number) matches = matches.filter((v) => v.policy_number === form.policy_number);
    return [...new Set(matches.map((v) => v.vehicle_year))].sort((a, b) => a - b);
  }, [allVehicles, form.policy_number]);
  const makeOptions = useMemo(
    () =>
      [...new Set(filterByOther('vehicle_make').map((v) => v.vehicle_make))].sort(),
    [filterByOther]
  );
  const modelOptions = useMemo(
    () =>
      [...new Set(filterByOther('vehicle_model').map((v) => v.vehicle_model))].sort(),
    [filterByOther]
  );
  const vinOptions = useMemo(() => {
    let matches = allVehicles;
    if (form.policy_number) matches = matches.filter((v) => v.policy_number === form.policy_number);
    return matches.map((v) => ({
      vin: v.vin,
      label: `${v.vehicle_year} ${v.vehicle_make} ${v.vehicle_model} (${v.vin})`,
    }));
  }, [allVehicles, form.policy_number]);

  useEffect(() => {
    setForm((prev) => {
      let next = { ...prev };
      let changed = false;
      if (prev.policy_number && !policyOptions.includes(prev.policy_number)) {
        next = { ...next, policy_number: '', vin: '', vehicle_year: undefined, vehicle_make: '', vehicle_model: '' };
        changed = true;
      }
      if (next.vehicle_year != null && !yearOptions.includes(next.vehicle_year)) {
        next = { ...next, vehicle_year: undefined, vin: '', vehicle_make: '', vehicle_model: '' };
        changed = true;
      }
      if (next.vehicle_make && !makeOptions.includes(next.vehicle_make)) {
        next = { ...next, vin: '', vehicle_model: '' };
        changed = true;
      }
      if (next.vehicle_model && !modelOptions.includes(next.vehicle_model)) {
        next = { ...next, vin: '' };
        changed = true;
      }
      if (next.vin && !vinOptions.some((o) => o.vin === next.vin)) {
        next = { ...next, vin: '' };
        changed = true;
      }
      return changed ? next : prev;
    });
  }, [policyOptions, yearOptions, makeOptions, modelOptions, vinOptions]);

  const handleVehicleSelect = useCallback(
    (vin: string) => {
      const v = allVehicles.find((ve) => ve.vin === vin);
      if (v) {
        setForm((prev) => ({
          ...prev,
          vin: v.vin,
          policy_number: v.policy_number,
          vehicle_year: v.vehicle_year,
          vehicle_make: v.vehicle_make,
          vehicle_model: v.vehicle_model,
        }));
      }
    },
    [allVehicles]
  );

  const handlePolicyChange = useCallback(
    (policyNumber: string) => {
      const policy = policies.find((p) => p.policy_number === policyNumber);
      if (policy?.vehicles.length === 1) {
        const v = policy.vehicles[0];
        setForm((prev) => ({
          ...prev,
          policy_number: policyNumber,
          vin: v.vin,
          vehicle_year: v.vehicle_year,
          vehicle_make: v.vehicle_make,
          vehicle_model: v.vehicle_model,
        }));
      } else if (policy?.vehicles.length) {
        const v = policy.vehicles[0];
        setForm((prev) => ({
          ...prev,
          policy_number: policyNumber,
          vin: v.vin,
          vehicle_year: v.vehicle_year,
          vehicle_make: v.vehicle_make,
          vehicle_model: v.vehicle_model,
        }));
      } else {
        updateField('policy_number', policyNumber);
      }
    },
    [policies, updateField]
  );

  const handleYearChange = useCallback(
    (year: string) => {
      updateField('vehicle_year', year ? parseInt(year, 10) : undefined);
    },
    [updateField]
  );

  const handleMakeChange = useCallback((make: string) => {
    updateField('vehicle_make', make);
  }, [updateField]);

  const handleModelChange = useCallback((model: string) => {
    updateField('vehicle_model', model);
  }, [updateField]);

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
    <div className="space-y-8 animate-fade-in">
      <PageHeader
        title="New Claim"
        subtitle="Submit a claim and watch it get routed and resolved in realtime"
      />

      <form onSubmit={handleSubmit} className="bg-gray-800/50 rounded-xl border border-gray-700/50 overflow-hidden">
        {/* Vehicle Information */}
        <div className="p-6 border-b border-gray-700/30">
          <h3 className="text-sm font-semibold text-gray-300 mb-4 flex items-center gap-2">
            <span>🚗</span> Vehicle Information
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {policies.length > 0 ? (
              <>
                <div>
                  <label htmlFor="policy_number" className={labelClasses}>
                    Policy Number <span className="text-red-400">*</span>
                  </label>
                  <PolicySelect
                    id="policy_number"
                    policies={policies}
                    value={form.policy_number}
                    onChange={handlePolicyChange}
                    required
                    className={selectClasses}
                  />
                </div>
                <div>
                  <label htmlFor="vehicle_year" className={labelClasses}>
                    Vehicle Year <span className="text-red-400">*</span>
                  </label>
                  <select
                    id="vehicle_year"
                    value={form.vehicle_year ?? ''}
                    onChange={(e) => handleYearChange(e.target.value)}
                    required
                    className={selectClasses}
                  >
                    <option value="">Select year…</option>
                    {yearOptions.map((y) => (
                      <option key={y} value={y}>
                        {y}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label htmlFor="vehicle_make" className={labelClasses}>
                    Vehicle Make <span className="text-red-400">*</span>
                  </label>
                  <select
                    id="vehicle_make"
                    value={form.vehicle_make}
                    onChange={(e) => handleMakeChange(e.target.value)}
                    required
                    className={selectClasses}
                  >
                    <option value="">Select make…</option>
                    {makeOptions.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label htmlFor="vehicle_model" className={labelClasses}>
                    Vehicle Model <span className="text-red-400">*</span>
                  </label>
                  <select
                    id="vehicle_model"
                    value={form.vehicle_model}
                    onChange={(e) => handleModelChange(e.target.value)}
                    required
                    className={selectClasses}
                  >
                    <option value="">Select model…</option>
                    {modelOptions.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label htmlFor="vin" className={labelClasses}>
                    VIN <span className="text-red-400">*</span>
                  </label>
                  <select
                    id="vin"
                    value={form.vin}
                    onChange={(e) => handleVehicleSelect(e.target.value)}
                    required
                    className={selectClasses}
                  >
                    <option value="">Select vehicle…</option>
                    {vinOptions.map((o) => (
                      <option key={o.vin} value={o.vin}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </div>
              </>
            ) : (
              <>
                <div>
                  <label htmlFor="policy_number" className={labelClasses}>
                    Policy Number <span className="text-red-400">*</span>
                  </label>
                  <input
                    id="policy_number"
                    type="text"
                    value={form.policy_number}
                    onChange={(e) => updateField('policy_number', e.target.value)}
                    required
                    className={inputClasses}
                    placeholder="POL-001"
                  />
                </div>
                <div>
                  <label htmlFor="vin" className={labelClasses}>
                    VIN <span className="text-red-400">*</span>
                  </label>
                  <input
                    id="vin"
                    type="text"
                    value={form.vin}
                    onChange={(e) => updateField('vin', e.target.value)}
                    required
                    className={inputClasses}
                    placeholder="1HGBH41JXMN109186"
                  />
                </div>
                <div>
                  <label htmlFor="vehicle_year" className={labelClasses}>
                    Vehicle Year <span className="text-red-400">*</span>
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
                    className={inputClasses}
                  />
                </div>
                <div>
                  <label htmlFor="vehicle_make" className={labelClasses}>
                    Vehicle Make <span className="text-red-400">*</span>
                  </label>
                  <input
                    id="vehicle_make"
                    type="text"
                    value={form.vehicle_make}
                    onChange={(e) => updateField('vehicle_make', e.target.value)}
                    required
                    className={inputClasses}
                    placeholder="Honda"
                  />
                </div>
                <div>
                  <label htmlFor="vehicle_model" className={labelClasses}>
                    Vehicle Model <span className="text-red-400">*</span>
                  </label>
                  <input
                    id="vehicle_model"
                    type="text"
                    value={form.vehicle_model}
                    onChange={(e) => updateField('vehicle_model', e.target.value)}
                    required
                    className={inputClasses}
                    placeholder="Accord"
                  />
                </div>
              </>
            )}
          </div>
        </div>

        {/* Incident Details */}
        <div className="p-6 border-b border-gray-700/30">
          <h3 className="text-sm font-semibold text-gray-300 mb-4 flex items-center gap-2">
            <span>📝</span> Incident Details
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5 mb-5">
            <div>
              <label htmlFor="incident_date" className={labelClasses}>
                Incident Date <span className="text-red-400">*</span>
              </label>
              <input
                id="incident_date"
                type="date"
                value={form.incident_date}
                onChange={(e) => updateField('incident_date', e.target.value)}
                required
                className={inputClasses}
              />
            </div>
            <div>
              <label htmlFor="estimated_damage" className={labelClasses}>
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
                className={inputClasses}
                placeholder="Optional"
              />
            </div>
          </div>

          <div className="space-y-5">
            <div>
              <label htmlFor="incident_description" className={labelClasses}>
                Incident Description <span className="text-red-400">*</span>
              </label>
              <textarea
                id="incident_description"
                value={form.incident_description}
                onChange={(e) => updateField('incident_description', e.target.value)}
                required
                rows={3}
                className={inputClasses}
                placeholder="Describe what happened…"
              />
            </div>

            <div>
              <label htmlFor="damage_description" className={labelClasses}>
                Damage Description <span className="text-red-400">*</span>
              </label>
              <textarea
                id="damage_description"
                value={form.damage_description}
                onChange={(e) => updateField('damage_description', e.target.value)}
                required
                rows={3}
                className={inputClasses}
                placeholder="Describe the vehicle damage…"
              />
            </div>
          </div>
        </div>

        {/* Attachments */}
        <div className="p-6 border-b border-gray-700/30">
          <h3 className="text-sm font-semibold text-gray-300 mb-4 flex items-center gap-2">
            <span>📎</span> Attachments
          </h3>
          <label
            htmlFor="attachments"
            className="flex flex-col items-center justify-center py-8 px-4 border-2 border-dashed border-gray-700 rounded-xl bg-gray-800/30 hover:bg-gray-800/50 hover:border-gray-600 transition-colors cursor-pointer"
          >
            <span className="text-3xl mb-2 opacity-40">📂</span>
            <span className="text-sm text-gray-400 mb-1">
              Drop files here or <span className="text-blue-400">browse</span>
            </span>
            <span className="text-xs text-gray-600">
              Photos, PDFs, estimates (optional)
            </span>
            <input
              id="attachments"
              type="file"
              multiple
              accept="image/*,.pdf"
              onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
              className="hidden"
            />
          </label>
          {files.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {files.map((f, i) => (
                <span
                  key={i}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-gray-800 text-xs text-gray-300 ring-1 ring-gray-700"
                >
                  📄 {f.name}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Error & Actions */}
        <div className="p-6">
          {error && (
            <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-4 mb-4 flex items-start gap-3">
              <span className="text-lg">⚠️</span>
              <p className="text-sm text-red-400">{error}</p>
            </div>
          )}

          <div className="flex gap-3">
            <button
              type="submit"
              disabled={submitting || (!!claimId && !done)}
              className="px-5 py-2.5 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-all active:scale-[0.98]"
            >
              {submitting ? 'Submitting…' : claimId && !done ? 'Processing…' : 'Submit Claim'}
            </button>
            {claimId && done && (
              <>
                <Link
                  to={`/claims/${claimId}`}
                  className="px-5 py-2.5 bg-emerald-600 text-white rounded-lg font-medium hover:bg-emerald-500 transition-all active:scale-[0.98]"
                >
                  View Claim
                </Link>
                <button
                  type="button"
                  onClick={resetForm}
                  className="px-5 py-2.5 border border-gray-700 rounded-lg font-medium text-gray-300 hover:bg-gray-800 transition-all active:scale-[0.98]"
                >
                  New Claim
                </button>
              </>
            )}
          </div>
        </div>
      </form>

      {/* Realtime processing view */}
      {claimId && (
        <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 overflow-hidden animate-slide-up">
          <div className="px-6 py-4 border-b border-gray-700/30 bg-gray-800/80">
            <h2 className="text-lg font-semibold text-gray-100">Processing in Realtime</h2>
            <p className="text-sm text-gray-500 mt-0.5">
              Claim {claimId} — routing and resolution updates stream live below
            </p>
          </div>

          <div className="p-6 space-y-6">
            {/* Status and routing */}
            <div className="flex flex-wrap items-center gap-4">
              <div className="flex items-center gap-2">
                <span className="text-sm text-gray-500">Status:</span>
                <StatusBadge status={claim?.status ?? 'pending'} />
              </div>
              {claim?.claim_type && (
                <div className="flex items-center gap-2">
                  <span className="text-sm text-gray-500">Routed to:</span>
                  <TypeBadge type={claim.claim_type} />
                </div>
              )}
              {!done && (
                <span className="inline-flex items-center gap-1.5 text-sm text-blue-400">
                  <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
                  Live
                </span>
              )}
            </div>

            {/* Audit timeline */}
            {history.length > 0 && (
              <div>
                <h3 className="text-sm font-medium text-gray-300 mb-3">Audit Log</h3>
                <ul className="space-y-2">
                  {history.map((evt, i) => (
                    <li
                      key={evt.id ?? i}
                      className="flex items-start gap-3 text-sm py-2.5 px-3 bg-gray-900/50 rounded-lg ring-1 ring-gray-700/30"
                    >
                      <span className="text-gray-500 shrink-0 text-xs">
                        {evt.created_at
                          ? new Date(evt.created_at).toLocaleTimeString()
                          : '—'}
                      </span>
                      <span className="font-medium text-gray-300">{evt.action}</span>
                      {evt.old_status && evt.new_status && (
                        <span className="text-gray-500">
                          {evt.old_status} → {evt.new_status}
                        </span>
                      )}
                      {evt.details && (
                        <span className="text-gray-500 truncate">{evt.details}</span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Workflow runs */}
            {workflows.length > 0 && (
              <div>
                <h3 className="text-sm font-medium text-gray-300 mb-3">Workflow Runs</h3>
                <div className="space-y-3">
                  {workflows.map((wf, i) => (
                    <div
                      key={wf.id ?? i}
                      className="p-4 border border-gray-700/50 rounded-lg bg-gray-900/30"
                    >
                      <div className="flex items-center gap-2 mb-2">
                        <TypeBadge type={wf.claim_type} />
                        {wf.created_at && (
                          <span className="text-xs text-gray-500">
                            {new Date(wf.created_at).toLocaleString()}
                          </span>
                        )}
                      </div>
                      {wf.router_output && (
                        <div className="mb-2">
                          <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Router</p>
                          <div className="bg-gray-900 rounded-lg p-3 ring-1 ring-gray-700/50">
                            <StructuredOutputDisplay value={wf.router_output} />
                          </div>
                        </div>
                      )}
                      {wf.workflow_output && (
                        <div>
                          <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Output</p>
                          <div className="bg-gray-900 rounded-lg p-3 max-h-48 overflow-y-auto ring-1 ring-gray-700/50">
                            <StructuredOutputDisplay value={wf.workflow_output} />
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {!claim && !done && !error && (
              <p className="text-sm text-gray-500 animate-pulse">Waiting for first update…</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
