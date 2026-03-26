import { useState, useRef, useEffect, useCallback } from 'react';
import ChatMessage from './ChatMessage';
import { streamChat } from '../api/client';
import type { ChatMessage as ChatMessageType, ChatStreamEvent, ChatToolCall } from '../api/types';

let _msgIdCounter = 0;
function nextMsgId(): string {
  return `msg-${++_msgIdCounter}-${Date.now()}`;
}

export default function ChatPanel() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessageType[]>([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef<(() => void) | null>(null);
  const isSendingRef = useRef(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const closePanel = useCallback(() => {
    setOpen(false);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        closePanel();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open, closePanel]);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Abort any active SSE stream on unmount to avoid state-update-after-unmount warnings
  useEffect(() => {
    return () => {
      if (abortRef.current) {
        abortRef.current();
        abortRef.current = null;
      }
    };
  }, []);

  // Focus input when panel opens
  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [open]);

  const messagesRef = useRef(messages);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text || isSendingRef.current) return;

    isSendingRef.current = true;

    const prev = messagesRef.current;
    const userMsg: ChatMessageType = {
      id: nextMsgId(),
      role: 'user',
      content: text,
    };

    const assistantMsg: ChatMessageType = {
      id: nextMsgId(),
      role: 'assistant',
      content: '',
      toolCalls: [],
    };

    const newMessages = [...prev, userMsg, assistantMsg];
    setMessages(newMessages);
    setInput('');
    setStreaming(true);

    // Build conversation for the API (only role + content)
    const apiMessages = newMessages
      .filter((m) => m.content || m.role === 'user')
      .map((m) => ({ role: m.role, content: m.content }));

    const currentToolCalls: ChatToolCall[] = [];
    let currentContent = '';

    const abort = streamChat(
      apiMessages,
      (event: ChatStreamEvent) => {
        switch (event.type) {
          case 'text':
            currentContent += event.content ?? '';
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last && last.role === 'assistant') {
                updated[updated.length - 1] = {
                  ...last,
                  content: currentContent,
                  toolCalls: [...currentToolCalls],
                };
              }
              return updated;
            });
            break;

          case 'tool_call':
            currentToolCalls.push({
              id: event.id,
              name: event.name ?? 'unknown',
              args: event.args,
            });
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last && last.role === 'assistant') {
                updated[updated.length - 1] = {
                  ...last,
                  toolCalls: [...currentToolCalls],
                };
              }
              return updated;
            });
            break;

          case 'tool_result': {
            const idx = event.id
              ? currentToolCalls.findIndex((tc) => tc.id === event.id && tc.result === undefined)
              : currentToolCalls.findIndex(
                  (tc) => tc.name === event.name && tc.result === undefined
                );
            if (idx >= 0) {
              currentToolCalls[idx] = { ...currentToolCalls[idx], result: event.result };
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last && last.role === 'assistant') {
                  updated[updated.length - 1] = {
                    ...last,
                    toolCalls: [...currentToolCalls],
                  };
                }
                return updated;
              });
            }
            break;
          }

          case 'done':
            isSendingRef.current = false;
            setStreaming(false);
            break;

          case 'error':
            currentContent += `\n\n⚠️ Error: ${event.message ?? 'Unknown error'}`;
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last && last.role === 'assistant') {
                updated[updated.length - 1] = {
                  ...last,
                  content: currentContent,
                };
              }
              return updated;
            });
            isSendingRef.current = false;
            setStreaming(false);
            break;

          default: {
            const _exhaustive: never = event;
            void _exhaustive;
            break;
          }
        }
      },
      (err) => {
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last && last.role === 'assistant') {
            updated[updated.length - 1] = {
              ...last,
              content: `⚠️ Connection error: ${err.message}`,
            };
          }
          return updated;
        });
        isSendingRef.current = false;
        setStreaming(false);
      },
    );

    abortRef.current = abort;
  }, [input]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleClear = () => {
    if (streaming && abortRef.current) {
      abortRef.current();
      isSendingRef.current = false;
      setStreaming(false);
    }
    setMessages([]);
  };

  // Floating button (collapsed)
  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Open chat assistant"
        className="fixed bottom-6 right-6 z-50 w-14 h-14 rounded-full bg-blue-600 text-white shadow-lg shadow-blue-600/25 hover:bg-blue-500 hover:shadow-blue-500/30 transition-all duration-200 flex items-center justify-center group"
      >
        <svg className="w-6 h-6 group-hover:scale-110 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
        </svg>
        {messages.length > 0 && (
          <span className="absolute -top-1 -right-1 w-5 h-5 bg-blue-500 rounded-full text-[10px] font-bold flex items-center justify-center" title="Conversation messages">
            {messages.length}
          </span>
        )}
      </button>
    );
  }

  // Expanded panel
  return (
    <div
      role="dialog"
      aria-modal="false"
      aria-label="Claims assistant chat"
      className="fixed bottom-4 right-4 sm:bottom-6 sm:right-6 z-50 w-[min(100vw-2rem,420px)] max-h-[min(100dvh-2rem,560px)] h-[min(100dvh-2rem,560px)] bg-gray-900 border border-gray-700/60 rounded-2xl shadow-2xl shadow-black/40 flex flex-col overflow-hidden animate-fade-in"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-gray-800/80 border-b border-gray-700/50">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-blue-600 flex items-center justify-center">
            <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
            </svg>
          </div>
          <div>
            <h3 className="text-sm font-semibold text-gray-100">Claims Assistant</h3>
            <p className="text-[11px] text-gray-500">AI-powered help</p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          {messages.length > 0 && (
            <button
              type="button"
              onClick={handleClear}
              aria-label="Clear conversation"
              className="p-1.5 text-gray-400 hover:text-gray-200 hover:bg-gray-700/50 rounded-lg transition-colors"
              title="Clear conversation"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          )}
          <button
            type="button"
            onClick={closePanel}
            aria-label="Close chat"
            className="p-1.5 text-gray-400 hover:text-gray-200 hover:bg-gray-700/50 rounded-lg transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center px-4">
            <div className="w-12 h-12 rounded-full bg-blue-600/10 flex items-center justify-center mb-3">
              <svg className="w-6 h-6 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
              </svg>
            </div>
            <p className="text-sm font-medium text-gray-300 mb-1">Claims Assistant</p>
            <p className="text-xs text-gray-500 mb-4">Ask me about claims, policies, system config, or anything else.</p>
            <div className="space-y-1.5 w-full">
              {[
                'How many claims are in the system?',
                'Show me the review queue',
                'What are the escalation thresholds?',
              ].map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => {
                    setInput(suggestion);
                    setTimeout(() => inputRef.current?.focus(), 50);
                  }}
                  className="w-full text-left px-3 py-2 text-xs text-gray-400 bg-gray-800/50 border border-gray-700/40 rounded-lg hover:bg-gray-800 hover:text-gray-300 transition-colors"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((msg) => (
          <ChatMessage key={msg.id} message={msg} />
        ))}
        {streaming && messages.length > 0 && (
          <div className="flex justify-start">
            <div className="flex items-center gap-1.5 px-3 py-2 text-xs text-gray-500">
              <span className="inline-flex gap-0.5">
                <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="px-4 py-3 bg-gray-800/50 border-t border-gray-700/50">
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about claims, policies..."
            rows={1}
            disabled={streaming}
            className="flex-1 resize-none bg-gray-800 border border-gray-700 rounded-xl px-3 py-2.5 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500/50 focus:border-blue-500/50 transition-colors disabled:opacity-50 max-h-24 overflow-y-auto"
            style={{ minHeight: '40px' }}
          />
          <button
            type="button"
            onClick={handleSend}
            disabled={!input.trim() || streaming}
            aria-label="Send message"
            className="shrink-0 w-9 h-9 rounded-xl bg-blue-600 text-white flex items-center justify-center hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            <svg className="w-4 h-4 rotate-90" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19V5m0 0l-7 7m7-7l7 7" />
            </svg>
          </button>
        </div>
        <p className="mt-1.5 text-[10px] text-gray-600 text-center">
          Shift+Enter for new line · Enter to send
        </p>
      </div>
    </div>
  );
}
