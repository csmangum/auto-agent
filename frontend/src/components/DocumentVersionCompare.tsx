import { useMemo, useState } from 'react';
import type { ClaimDocument } from '../api/types';
import { formatDateTime } from '../utils/date';

interface DocumentVersionCompareProps {
  documents: ClaimDocument[];
}

function metaLines(doc: ClaimDocument): string[] {
  return [
    `ID: ${doc.id}`,
    `Version: ${doc.version ?? 1}`,
    `Type: ${doc.document_type}`,
    `Review: ${doc.review_status}`,
    doc.received_from ? `From: ${doc.received_from}` : '',
    doc.received_date ? `Received: ${doc.received_date}` : '',
    doc.created_at ? `Created: ${formatDateTime(doc.created_at)}` : '',
    doc.privileged ? 'Privileged: yes' : '',
  ].filter(Boolean);
}

export default function DocumentVersionCompare({ documents }: DocumentVersionCompareProps) {
  const [leftId, setLeftId] = useState<string>('');
  const [rightId, setRightId] = useState<string>('');

  const sorted = useMemo(
    () => [...documents].sort((a, b) => a.id - b.id),
    [documents]
  );

  const byId = useMemo(() => {
    const m = new Map<number, ClaimDocument>();
    for (const d of documents) m.set(d.id, d);
    return m;
  }, [documents]);

  const left = leftId ? byId.get(Number(leftId)) : undefined;
  const right = rightId ? byId.get(Number(rightId)) : undefined;

  if (sorted.length < 2) {
    return (
      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
        <h3 className="text-sm font-semibold text-gray-300 mb-2">Compare versions</h3>
        <p className="text-sm text-gray-500">
          Upload at least two document rows (e.g. revised file with the same storage key and a higher
          version) to compare metadata and extracted data side by side.
        </p>
      </div>
    );
  }

  return (
    <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
      <h3 className="text-sm font-semibold text-gray-300 mb-4">Compare versions</h3>
      <p className="text-xs text-gray-500 mb-4">
        Pick two document records. For structured OCR payloads, compare the extracted JSON below.
        Binary files are not diffed in-app—open both &quot;View&quot; links in separate tabs if needed.
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <div>
          <label className="block text-xs text-gray-500 mb-1">Version A</label>
          <select
            value={leftId}
            onChange={(e) => setLeftId(e.target.value)}
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            <option value="">Select…</option>
            {sorted.map((d) => (
              <option key={d.id} value={String(d.id)}>
                #{d.id} · v{d.version ?? 1} · {(d.storage_key || '').split('/').pop()}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Version B</label>
          <select
            value={rightId}
            onChange={(e) => setRightId(e.target.value)}
            className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            <option value="">Select…</option>
            {sorted.map((d) => (
              <option key={d.id} value={String(d.id)}>
                #{d.id} · v{d.version ?? 1} · {(d.storage_key || '').split('/').pop()}
              </option>
            ))}
          </select>
        </div>
      </div>

      {left && right && left.id !== right.id && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="rounded-lg bg-gray-900/50 ring-1 ring-gray-700/50 p-3 min-w-0">
            <p className="text-xs font-medium text-blue-400 mb-2">A · v{left.version ?? 1}</p>
            <ul className="text-xs text-gray-400 space-y-1 mb-3 font-mono">
              {metaLines(left).map((line, i) => (
                <li key={`l-${i}`}>{line}</li>
              ))}
            </ul>
            <p className="text-xs text-gray-500 mb-1">extracted_data</p>
            <pre className="text-xs text-gray-300 overflow-x-auto max-h-64 overflow-y-auto p-2 rounded bg-black/30 border border-gray-700/50">
              {left.extracted_data != null
                ? JSON.stringify(left.extracted_data, null, 2)
                : '—'}
            </pre>
          </div>
          <div className="rounded-lg bg-gray-900/50 ring-1 ring-gray-700/50 p-3 min-w-0">
            <p className="text-xs font-medium text-emerald-400 mb-2">B · v{right.version ?? 1}</p>
            <ul className="text-xs text-gray-400 space-y-1 mb-3 font-mono">
              {metaLines(right).map((line, i) => (
                <li key={`r-${i}`}>{line}</li>
              ))}
            </ul>
            <p className="text-xs text-gray-500 mb-1">extracted_data</p>
            <pre className="text-xs text-gray-300 overflow-x-auto max-h-64 overflow-y-auto p-2 rounded bg-black/30 border border-gray-700/50">
              {right.extracted_data != null
                ? JSON.stringify(right.extracted_data, null, 2)
                : '—'}
            </pre>
          </div>
        </div>
      )}

      {left && right && left.id === right.id && (
        <p className="text-sm text-amber-400/90">Choose two different document rows to compare.</p>
      )}
    </div>
  );
}
