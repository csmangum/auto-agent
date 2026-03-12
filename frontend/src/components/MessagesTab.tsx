import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import EmptyState from './EmptyState';
import { formatDateTime } from '../utils/date';
import { queryKeys } from '../api/queries';
import type { FollowUpMessage } from '../api/types';
import { postJSON } from '../api/client';

interface MessagesTabProps {
  followUps: FollowUpMessage[];
  claimId: string;
  accentColor: 'emerald' | 'amber' | 'purple';
  senderLabel: string;
  emptyTitle?: string;
  emptyDescription?: string;
}

export default function MessagesTab({
  followUps,
  claimId,
  accentColor,
  senderLabel,
  emptyTitle = 'No messages',
  emptyDescription = 'No messages yet.',
}: MessagesTabProps) {
  const [responseText, setResponseText] = useState('');
  const [respondingTo, setRespondingTo] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitResult, setSubmitResult] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const colorClasses = {
    emerald: {
      text: 'text-emerald-400',
      hover: 'hover:text-emerald-300',
      bg: 'bg-emerald-600',
      hoverBg: 'hover:bg-emerald-500',
      ring: 'focus:ring-emerald-500/40',
      resultBg: 'bg-emerald-500/10',
      resultText: 'text-emerald-400',
      borderBg: 'bg-emerald-500/5',
      borderColor: 'border-emerald-500/10',
      statusBg: 'bg-emerald-500/20',
      statusText: 'text-emerald-400',
    },
    amber: {
      text: 'text-amber-400',
      hover: 'hover:text-amber-300',
      bg: 'bg-amber-600',
      hoverBg: 'hover:bg-amber-500',
      ring: 'focus:ring-amber-500/40',
      resultBg: 'bg-amber-500/10',
      resultText: 'text-amber-400',
      borderBg: 'bg-amber-500/5',
      borderColor: 'border-amber-500/10',
      statusBg: 'bg-amber-500/20',
      statusText: 'text-amber-400',
    },
    purple: {
      text: 'text-purple-400',
      hover: 'hover:text-purple-300',
      bg: 'bg-purple-600',
      hoverBg: 'hover:bg-purple-500',
      ring: 'focus:ring-purple-500/40',
      resultBg: 'bg-purple-500/10',
      resultText: 'text-purple-400',
      borderBg: 'bg-purple-500/5',
      borderColor: 'border-purple-500/10',
      statusBg: 'bg-purple-500/20',
      statusText: 'text-purple-400',
    },
  };

  const colors = colorClasses[accentColor];

  async function handleRespond(messageId: number) {
    if (!responseText.trim()) return;
    setSubmitting(true);
    setSubmitResult(null);
    try {
      await postJSON(`/claims/${claimId}/follow-up/record-response`, {
        message_id: messageId,
        response_content: responseText.trim(),
      });
      setSubmitResult('Response submitted');
      setResponseText('');
      setRespondingTo(null);
      
      await queryClient.invalidateQueries({ queryKey: queryKeys.claim(claimId) });
      await queryClient.invalidateQueries({ queryKey: queryKeys.claimHistory(claimId) });
    } catch (err) {
      setSubmitResult(`Error: ${err instanceof Error ? err.message : 'Unknown error'}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-4">
      {submitResult && (
        <div className={`text-sm px-4 py-2 rounded-lg ${
          submitResult.startsWith('Error') ? 'bg-red-500/10 text-red-400' : `${colors.resultBg} ${colors.resultText}`
        }`}>
          {submitResult}
        </div>
      )}

      {followUps.length === 0 ? (
        <EmptyState
          icon="✉️"
          title={emptyTitle}
          description={emptyDescription}
        />
      ) : (
        followUps.map((msg) => (
          <div key={msg.id} className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-5">
            <div className="flex items-center justify-between gap-2 mb-3">
              <div className="flex items-center gap-2">
                <span className={`text-xs font-medium ${colors.text}`}>{senderLabel}</span>
                <span className={`text-xs px-2 py-0.5 rounded ${
                  msg.status === 'responded' ? 'bg-emerald-500/20 text-emerald-400'
                    : msg.status === 'sent' ? `${colors.statusBg} ${colors.statusText}`
                    : 'bg-gray-500/20 text-gray-400'
                }`}>
                  {msg.status === 'sent' 
                    ? (accentColor === 'emerald' ? 'Awaiting your response' : accentColor === 'amber' ? 'Action needed' : 'Response required')
                    : msg.status}
                </span>
              </div>
              <span className="text-xs text-gray-500">{formatDateTime(msg.created_at)}</span>
            </div>

            <div className="bg-gray-900/50 rounded-lg p-3 mb-3">
              <p className="text-sm text-gray-300">{msg.message_content}</p>
            </div>

            {msg.response_content ? (
              <div className={`${colors.borderBg} border ${colors.borderColor} rounded-lg p-3`}>
                <p className={`text-xs ${colors.text} mb-1`}>Your response</p>
                <p className="text-sm text-gray-300">{msg.response_content}</p>
              </div>
            ) : msg.status === 'sent' ? (
              respondingTo === msg.id ? (
                <div className="space-y-2">
                  <textarea
                    value={responseText}
                    onChange={(e) => setResponseText(e.target.value)}
                    placeholder="Type your response..."
                    rows={3}
                    className={`w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-300 placeholder:text-gray-600 focus:outline-none focus:ring-1 ${colors.ring} resize-none`}
                  />
                  <div className="flex gap-2">
                    <button type="button" onClick={() => handleRespond(msg.id)} disabled={submitting || !responseText.trim()}
                      className={`px-3 py-1.5 ${colors.bg} text-white text-xs font-medium rounded-lg ${colors.hoverBg} disabled:opacity-50 transition-colors`}>
                      {submitting ? 'Sending...' : 'Send Response'}
                    </button>
                    <button type="button" onClick={() => { setRespondingTo(null); setResponseText(''); }}
                      className="px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200 transition-colors">
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <button type="button" onClick={() => { setRespondingTo(msg.id); setResponseText(''); }}
                  className={`text-xs font-medium ${colors.text} ${colors.hover} transition-colors`}>
                  {accentColor === 'emerald' ? 'Reply to this message →' : 'Reply →'}
                </button>
              )
            ) : null}
          </div>
        ))
      )}
    </div>
  );
}
