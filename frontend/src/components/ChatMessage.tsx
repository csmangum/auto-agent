import { useState, useId } from 'react';
import MarkdownRenderer from './MarkdownRenderer';
import type { ChatMessage as ChatMessageType, ChatToolCall } from '../api/types';

const TOOL_LABELS: Record<string, string> = {
  lookup_claim: 'Looking up claim',
  search_claims: 'Searching claims',
  get_claim_history: 'Getting claim history',
  get_claim_notes: 'Getting claim notes',
  get_claims_stats: 'Getting statistics',
  get_system_config: 'Getting system config',
  lookup_policy: 'Looking up policy',
  explain_escalation: 'Investigating escalation',
  get_review_queue: 'Checking review queue',
};

function ToolCallIndicator({ toolCall }: { toolCall: ChatToolCall }) {
  const [expanded, setExpanded] = useState(false);
  const uid = useId();
  const label = TOOL_LABELS[toolCall.name] || toolCall.name;
  const argsStr = toolCall.args ? Object.entries(toolCall.args).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(', ') : '';
  const resultId = `tool-result-${uid}`;

  return (
    <div className="my-1.5">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        aria-controls={resultId}
        className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-300 transition-colors"
      >
        <span className="text-blue-400">🔧</span>
        <span>{label}{argsStr ? ` (${argsStr})` : ''}</span>
        <svg
          className={`w-3 h-3 transition-transform ${expanded ? 'rotate-90' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
      </button>
      {expanded && toolCall.result != null && (
        <pre id={resultId} className="mt-1 p-2 bg-gray-900/80 rounded text-[11px] text-gray-400 overflow-x-auto max-h-40 overflow-y-auto">
          {typeof toolCall.result === 'string'
            ? toolCall.result
            : JSON.stringify(toolCall.result, null, 2)}
        </pre>
      )}
    </div>
  );
}

interface ChatMessageProps {
  message: ChatMessageType;
}

export default function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === 'user';

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[85%] rounded-xl px-3.5 py-2.5 text-sm ${
          isUser
            ? 'bg-blue-600 text-white rounded-br-sm'
            : 'bg-gray-800 text-gray-200 border border-gray-700/50 rounded-bl-sm'
        }`}
      >
        {/* Tool calls (shown before assistant text) */}
        {!isUser && message.toolCalls && message.toolCalls.length > 0 && (
          <div className="mb-2 border-b border-gray-700/50 pb-2">
            {message.toolCalls.map((tc, i) => (
              <ToolCallIndicator key={`${tc.name}-${i}`} toolCall={tc} />
            ))}
          </div>
        )}

        {/* Message content */}
        {isUser ? (
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : (
          <div className="chat-markdown prose prose-invert prose-sm max-w-none">
            <MarkdownRenderer content={message.content} />
          </div>
        )}
      </div>
    </div>
  );
}
