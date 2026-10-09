import { useEffect, useRef, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Sparkles, X, Send, Trash2, AlertTriangle } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import {
  sendAssistantChat, getAssistantConversation, clearAssistantConversation,
  confirmAssistantAction, denyAssistantAction,
  type AiMessage, type PendingAction,
} from '../api/assistant';

// Mirrors services/ai_prompt.py::_PAGE_INFO keys on the backend — keep in sync so the
// system prompt's per-page knowledge actually matches what the user is looking at.
const ROUTE_TO_PAGE_NAME: Record<string, string> = {
  '/dashboard': 'Overview',
  '/devices': 'Devices',
  '/alerts': 'Alerts',
  '/tickets': 'Tickets',
  '/customers': 'Customers',
  '/patches': 'OS Patches',
  '/scripts': 'Scripts',
  '/automation': 'Automation',
  '/reports': 'Reports',
  '/billing': 'Billing',
  '/admin': 'Admin Panel',
  '/network': 'Network Discovery',
  '/software-patches': 'Software Patches',
  '/terminal': 'Remote Terminal',
  '/disk': 'Disk Management',
  '/maintenance': 'Maintenance',
  '/client-portal': 'Client Tickets',
  '/profile': 'My Profile',
};

const RESTRICTED_PAGES = new Set(['Remote Terminal', 'Scripts']);

// Mirrors services/ai_prompt.py::_PAGE_ALLOWED_ROLES — cosmetic only (hides the button
// so a role never hits a real 403), the server is the actual enforcement point.
const PAGE_ALLOWED_ROLES: Record<string, string[]> = {
  'Billing': ['admin', 'technician', 'superadmin'],
  'Admin Panel': ['admin', 'superadmin'],
  'Remote Terminal': ['admin', 'technician', 'superadmin'],
  'Automation': ['admin', 'technician', 'superadmin'],
};

function pageNameForPath(pathname: string): string {
  const match = Object.keys(ROUTE_TO_PAGE_NAME).find((p) => pathname.startsWith(p));
  return match ? ROUTE_TO_PAGE_NAME[match] : 'Overview';
}

function fmtTime(iso: string | null): string {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

function errorReason(err: unknown): string {
  const status = (err as { response?: { status?: number } })?.response?.status;
  if (status === 503) return 'The AI assistant is currently disabled or not configured. Contact your administrator.';
  if (status === 429) return 'The assistant is busy right now — please wait a moment and try again.';
  if (status === 403) return "You don't have permission to use the assistant on this page.";
  if (status === 409) return 'That action already happened or has expired.';
  return 'Assistant temporarily unavailable. Please try again.';
}

interface LocalMessage {
  role: 'user' | 'assistant';
  content: string;
  warning?: boolean;
  ts: string;
}

export default function AiAssistant() {
  const { user } = useAuth();
  const location = useLocation();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<LocalMessage[]>([]);
  const [suggested, setSuggested] = useState<string[]>([]);
  const [pending, setPending] = useState<PendingAction | undefined>(undefined);
  const [hydrated, setHydrated] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const page = pageNameForPath(location.pathname);
  const role = user?.role ?? 'viewer';
  const allowedRoles = PAGE_ALLOWED_ROLES[page];
  const blockedByRole = !!allowedRoles && role !== 'superadmin' && !allowedRoles.includes(role);

  const conversationQuery = useQuery({
    queryKey: ['assistant', 'conversation'],
    queryFn: getAssistantConversation,
    enabled: !!user,
    staleTime: Infinity,
  });

  useEffect(() => {
    if (!hydrated && conversationQuery.data) {
      const loaded: LocalMessage[] = conversationQuery.data.messages
        .filter((m: AiMessage) => m.role === 'user' || m.role === 'assistant')
        .map((m: AiMessage) => ({
          role: m.role as 'user' | 'assistant',
          content: m.content,
          warning: m.contains_warning,
          ts: fmtTime(m.created_at),
        }));
      setMessages(loaded);
      setHydrated(true);
    }
  }, [conversationQuery.data, hydrated]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, pending, open]);

  const chatMutation = useMutation({
    mutationFn: (message: string) => sendAssistantChat(message, page, {}),
    onSuccess: (data) => {
      setMessages((prev) => [...prev, {
        role: 'assistant', content: data.reply, warning: data.contains_warning, ts: fmtTime(new Date().toISOString()),
      }]);
      setSuggested(data.suggested_actions || []);
      setPending(data.pending_action);
    },
    onError: (err) => {
      setMessages((prev) => [...prev, { role: 'assistant', content: errorReason(err), ts: fmtTime(new Date().toISOString()) }]);
    },
  });

  const confirmMutation = useMutation({
    mutationFn: (actionId: string) => confirmAssistantAction(actionId),
    onSuccess: () => {
      setMessages((prev) => [...prev, { role: 'assistant', content: 'Done — the action was completed.', ts: fmtTime(new Date().toISOString()) }]);
      setPending(undefined);
    },
    onError: (err) => {
      setMessages((prev) => [...prev, { role: 'assistant', content: errorReason(err), ts: fmtTime(new Date().toISOString()) }]);
      setPending(undefined);
    },
  });

  const denyMutation = useMutation({
    mutationFn: (actionId: string) => denyAssistantAction(actionId),
    onSuccess: () => {
      setMessages((prev) => [...prev, { role: 'assistant', content: "Okay, I won't do that.", ts: fmtTime(new Date().toISOString()) }]);
      setPending(undefined);
    },
  });

  const clearMutation = useMutation({
    mutationFn: clearAssistantConversation,
    onSuccess: () => {
      setMessages([]);
      setSuggested([]);
      setPending(undefined);
      qc.invalidateQueries({ queryKey: ['assistant', 'conversation'] });
    },
  });

  function submit(text: string) {
    const trimmed = text.trim();
    if (!trimmed || chatMutation.isPending) return;
    setMessages((prev) => [...prev, { role: 'user', content: trimmed, ts: fmtTime(new Date().toISOString()) }]);
    setInput('');
    chatMutation.mutate(trimmed);
  }

  if (!user || blockedByRole) return null;

  return (
    <>
      <button
        onClick={() => setOpen((o) => !o)}
        className="fixed bottom-5 right-5 z-50 flex items-center gap-2 rounded-full bg-brand-600 text-white px-4 py-3 shadow-lg hover:bg-brand-700 transition-colors"
      >
        {open ? <X size={18} /> : <Sparkles size={18} />}
        <span className="text-sm font-medium hidden sm:inline">{open ? 'Close Assistant' : 'AI Assistant'}</span>
      </button>

      {open && (
        <div className="fixed bottom-20 right-5 z-50 w-[min(92vw,380px)] h-[min(70vh,560px)] bg-white rounded-xl shadow-2xl border border-gray-200 flex flex-col overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100 bg-brand-800 text-white">
            <p className="text-sm font-semibold">AI Assistant</p>
            <p className="text-[11px] text-brand-200">AI may make mistakes — verify before acting</p>
          </div>

          <div ref={scrollRef} className="flex-1 overflow-y-auto px-3 py-3 space-y-3">
            {messages.length === 0 && (
              <div className="text-center text-xs text-gray-400 border border-dashed border-gray-200 rounded-lg py-6">
                Ask me anything about this page
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[85%] rounded-lg px-3 py-2 text-[13px] leading-relaxed whitespace-pre-wrap ${
                  m.role === 'user' ? 'bg-brand-600 text-white' : 'bg-gray-100 text-gray-800'
                }`}>
                  {m.warning && (
                    <div className="flex items-center gap-1 text-amber-700 bg-amber-50 rounded-sm px-2 py-1 mb-1 text-[11px] font-medium">
                      <AlertTriangle size={12} /> Verify before executing
                    </div>
                  )}
                  {m.content}
                  {m.ts && <div className="text-[10px] opacity-60 mt-1">{m.ts}</div>}
                </div>
              </div>
            ))}

            {pending && (
              <div className="border border-brand-200 bg-brand-50 rounded-lg p-3 space-y-2">
                {pending.contains_warning && (
                  <div className="flex items-center gap-1 text-amber-700 text-[11px] font-medium">
                    <AlertTriangle size={12} /> Potentially destructive — review carefully
                  </div>
                )}
                <p className="text-[13px] font-medium text-gray-800">Confirm action: {pending.summary}</p>
                <div className="flex gap-2">
                  <button
                    onClick={() => confirmMutation.mutate(pending.id)}
                    disabled={confirmMutation.isPending}
                    className="flex-1 bg-brand-600 hover:bg-brand-700 text-white text-xs font-semibold rounded-md py-1.5 disabled:opacity-50"
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => denyMutation.mutate(pending.id)}
                    disabled={denyMutation.isPending}
                    className="flex-1 bg-white border border-gray-300 text-gray-700 text-xs font-semibold rounded-md py-1.5 disabled:opacity-50"
                  >
                    Deny
                  </button>
                </div>
              </div>
            )}

            {chatMutation.isPending && (
              <div className="text-[11px] text-gray-400 px-1">Thinking…</div>
            )}
          </div>

          {RESTRICTED_PAGES.has(page) && (
            <div className="px-3 py-1.5 bg-amber-50 border-t border-amber-100 text-[11px] text-amber-700">
              Command/script suggestions are disabled on this page.
            </div>
          )}

          {suggested.length > 0 && (
            <div className="px-3 pt-2 flex flex-wrap gap-1.5">
              {suggested.slice(0, 3).map((s) => (
                <button
                  key={s}
                  onClick={() => { setSuggested([]); submit(`How do I: ${s}?`); }}
                  className="text-[11px] bg-brand-50 text-brand-700 border border-brand-100 rounded-full px-2.5 py-1 hover:bg-brand-100"
                >
                  {s}
                </button>
              ))}
            </div>
          )}

          <form
            onSubmit={(e) => { e.preventDefault(); submit(input); }}
            className="flex items-center gap-2 px-3 py-2.5 border-t border-gray-100"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value.slice(0, 800))}
              placeholder="Ask anything about this page…"
              className="flex-1 text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-hidden focus:ring-2 focus:ring-brand-300"
            />
            <button
              type="submit"
              disabled={!input.trim() || chatMutation.isPending}
              className="bg-brand-600 hover:bg-brand-700 text-white rounded-lg p-2 disabled:opacity-50"
            >
              <Send size={16} />
            </button>
            {messages.length > 0 && (
              <button
                type="button"
                onClick={() => clearMutation.mutate()}
                title="Clear conversation"
                className="text-gray-400 hover:text-gray-600 p-2"
              >
                <Trash2 size={16} />
              </button>
            )}
          </form>
        </div>
      )}
    </>
  );
}
