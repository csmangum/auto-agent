import { useState } from 'react';

export function ThirdPartyPortalDocumentUpload({
  claimId,
  onUploaded,
  uploadFn,
}: {
  claimId: string;
  onUploaded: () => void;
  uploadFn: (claimId: string, file: File) => Promise<unknown>;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setMsg(null);
    try {
      await uploadFn(claimId, file);
      setMsg('Document uploaded successfully.');
      setFile(null);
      onUploaded();
    } catch (err) {
      setMsg(`Error: ${err instanceof Error ? err.message : 'Upload failed'}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-6">
      <h3 className="text-sm font-semibold text-gray-300 mb-1">Upload document</h3>
      <p className="text-xs text-gray-500 mb-4">
        Submit supporting documents for your side of the claim (PDF, images, etc.).
      </p>
      <form onSubmit={handleSubmit} className="space-y-3">
        <input
          type="file"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="block w-full text-sm text-gray-400 file:mr-3 file:py-2 file:px-3 file:rounded-lg file:border-0 file:bg-gray-700 file:text-gray-200"
        />
        <button
          type="submit"
          disabled={busy || !file}
          className="px-4 py-2 bg-purple-600/90 text-white text-sm font-medium rounded-lg hover:bg-purple-500 disabled:opacity-50"
        >
          {busy ? 'Uploading…' : 'Upload'}
        </button>
        {msg && (
          <p
            className={`text-sm ${msg.startsWith('Error') ? 'text-red-400' : 'text-purple-400'}`}
          >
            {msg}
          </p>
        )}
      </form>
    </div>
  );
}
