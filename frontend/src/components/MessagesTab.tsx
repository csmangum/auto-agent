import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import EmptyState from './EmptyState';
import { formatDateTime } from '../utils/date';
import { queryKeys } from '../api/queries';
import type { FollowUpMessage } from '../api/types';
import { postClaimFollowUpResponse } from '../api/client';
import { MESSAGES_TAB_COLORS, type SimulationAccent } from '../utils/theme';
import { getErrorMessage } from '../utils/errorMessage';

interface MessagesTabProps {
  followUps: FollowUpMessage[];
  claimId: string;
  accentColor: SimulationAccent;
  senderLabel: string;
  emptyTitle?: string;
  emptyDescription?: string;
  /** When provided, used instead of postClaimFollowUpResponse (e.g. for portal) */
  onRespond?: (messageId: number, responseContent: string) => Promise<void>;
}

export default function MessagesTab({
  followUps,
  claimId,
  accentColor,
  senderLabel,
  emptyTitle = 'No messages',
  emptyDescription = 'No messages yet.',
  onRespond: customRespond,
}: MessagesTabProps) {
  const [responseText, setResponseText] = useState('');
  const [respondingTo, setRespondingTo] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const queryClient = useQueryClient();

  const colors = MESSAGES_TAB_COLORS[accentColor];

  async function handleRespond(messageId: number) {
    if (!responseText.trim()) return;
    setSubmitting(true);
    try {
      if (customRespond) {
        await customRespond(messageId, responseText.trim());
      } else {
        await postClaimFollowUpResponse(claimId, {
          message_id: messageId,
          response_content: responseText.trim(),
        });
        await queryClient.invalidateQueries({ queryKey: queryKeys.claim(claimId) });
        await queryClient.invalidateQueries({ queryKey: queryKeys.claimHistory(claimId) });
      }
      toast.success('Response sent');
      setResponseText('');
      setRespondingTo(null);
    } catch (err) {
      toast.error(getErrorMessage(err, 'Failed to send response'));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-4">
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
                  msg.status === 'responded' || msg.status === 'sent'
                    ? `${colors.statusBg} ${colors.statusText}`
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
