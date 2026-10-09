import { useState, useRef, useEffect } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { Terminal, Send, X } from 'lucide-react';
import api from '../api/client';
import type { Device } from '../api/types';
import { apiErrorMessage } from '../api/errors';

interface OutputRow {
  id: number;
  content: string;
  stream: 'stdout' | 'stderr' | 'system';
}

interface SessionState {
  sessionId: string;
  deviceId: string;
  deviceName: string;
}

export default function TerminalPage() {
  const [selectedDevice, setSelectedDevice] = useState('');
  const [session, setSession] = useState<SessionState | null>(null);
  const [cmd, setCmd] = useState('');
  const [cmdHistory, setCmdHistory] = useState<string[]>([]);
  const [historyIdx, setHistoryIdx] = useState(-1);
  const [outputRows, setOutputRows] = useState<OutputRow[]>([]);
  const lastOutputIdRef = useRef(0);
  const outputRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Reset output when session changes
  useEffect(() => {
    setOutputRows([]);
    lastOutputIdRef.current = 0;
  }, [session?.sessionId]);

  // Auto-scroll on new output
  useEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight;
    }
  }, [outputRows]);

  const { data: devicesData } = useQuery<{ items: Device[] }>({
    queryKey: ['devices-online'],
    queryFn: () => api.get('/devices/', { params: { per_page: 100 } }).then((r) => r.data),
  });

  const onlineDevices = (devicesData?.items ?? []).filter((d) => d.is_online && !d.is_agentless);

  // Poll output every 2s while session is active
  const { data: outputData } = useQuery({
    queryKey: ['terminal-output', session?.sessionId],
    queryFn: () =>
      api
        .get(`/terminal/sessions/${session!.sessionId}/output`, {
          params: { after: lastOutputIdRef.current },
        })
        .then((r) => r.data),
    enabled: !!session?.sessionId,
    refetchInterval: 2000,
    staleTime: 0,
  });

  useEffect(() => {
    if (!outputData?.output?.length) return;
    setOutputRows((prev) => {
      const existingIds = new Set(prev.map((r) => r.id));
      const fresh = (outputData.output as OutputRow[]).filter((r) => !existingIds.has(r.id));
      if (!fresh.length) return prev;
      lastOutputIdRef.current = fresh[fresh.length - 1].id;
      return [...prev, ...fresh];
    });
  }, [outputData]);

  const openSession = useMutation({
    mutationFn: (device_id: string) =>
      api.post('/terminal/sessions', { device_id }).then((r) => r.data),
    onSuccess: (data, device_id) => {
      const dev = onlineDevices.find((d) => d.id === device_id);
      setSession({
        sessionId: data.session_id ?? data.id,
        deviceId: device_id,
        deviceName: dev?.display_name || dev?.hostname || device_id,
      });
      setTimeout(() => inputRef.current?.focus(), 100);
    },
  });

  const sendCmd = useMutation({
    mutationFn: ({ sessionId, command }: { sessionId: string; command: string }) =>
      api.post(`/terminal/sessions/${sessionId}/commands`, { command }).then((r) => r.data),
    onSuccess: (_data, vars) => {
      setCmdHistory((prev) => [vars.command, ...prev].slice(0, 50));
      setCmd('');
      setHistoryIdx(-1);
    },
  });

  const closeSession = useMutation({
    mutationFn: (sessionId: string) => api.delete(`/terminal/sessions/${sessionId}`),
    onSuccess: () => {
      setSession(null);
      setOutputRows([]);
      lastOutputIdRef.current = 0;
    },
  });

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && cmd.trim() && session && !sendCmd.isPending) {
      sendCmd.mutate({ sessionId: session.sessionId, command: cmd.trim() });
    }
    if (e.key === 'ArrowUp') {
      const newIdx = Math.min(historyIdx + 1, cmdHistory.length - 1);
      setHistoryIdx(newIdx);
      setCmd(cmdHistory[newIdx] ?? '');
    }
    if (e.key === 'ArrowDown') {
      const newIdx = Math.max(historyIdx - 1, -1);
      setHistoryIdx(newIdx);
      setCmd(newIdx === -1 ? '' : (cmdHistory[newIdx] ?? ''));
    }
  };

  const streamClass = (stream: string) => {
    if (stream === 'stderr') return 'text-red-400';
    if (stream === 'system') return 'text-gray-500';
    return 'text-gray-200';
  };

  return (
    <div className="p-6 space-y-5">
      <div>
        <h1 className="text-xl font-bold text-gray-900">Remote Terminal</h1>
        <p className="text-sm text-gray-500">
          Execute shell commands on managed devices — all commands are audit-logged
        </p>
      </div>

      {!session ? (
        <div className="max-w-sm space-y-3">
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1">Target Device</label>
            <select
              value={selectedDevice}
              onChange={(e) => setSelectedDevice(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-brand-400 bg-white"
            >
              <option value="">Select online device…</option>
              {onlineDevices.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.display_name || d.hostname}
                </option>
              ))}
            </select>
          </div>
          <button
            onClick={() => openSession.mutate(selectedDevice)}
            disabled={!selectedDevice || openSession.isPending}
            className="flex items-center gap-2 px-4 py-2 bg-brand-500 text-white text-sm font-semibold rounded-lg hover:bg-brand-600 disabled:opacity-50 transition"
          >
            <Terminal size={15} />
            {openSession.isPending ? 'Connecting…' : 'Open Terminal'}
          </button>
          {openSession.isError && (
            <p className="text-xs text-red-600">
              {apiErrorMessage(openSession.error, 'Failed to open session')}
            </p>
          )}
        </div>
      ) : (
        <div className="flex flex-col h-[calc(100vh-200px)] bg-gray-900 rounded-xl overflow-hidden border border-gray-700">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-2.5 bg-gray-800 border-b border-gray-700">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
              <span className="text-sm font-mono text-green-400">{session.deviceName}</span>
              <span className="text-xs text-gray-500 font-mono">· session active</span>
            </div>
            <button
              onClick={() => closeSession.mutate(session.sessionId)}
              className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-red-400 transition"
            >
              <X size={13} />
              Disconnect
            </button>
          </div>

          {/* Output */}
          <div ref={outputRef} className="flex-1 overflow-y-auto p-4 font-mono text-sm">
            {outputRows.length === 0 && (
              <p className="text-gray-600 text-xs">Waiting for output…</p>
            )}
            {outputRows.map((row) => (
              <pre
                key={row.id}
                className={`whitespace-pre-wrap leading-relaxed ${streamClass(row.stream)}`}
              >
                {row.content}
              </pre>
            ))}
            {sendCmd.isPending && (
              <span className="text-yellow-400 text-xs animate-pulse">▌</span>
            )}
          </div>

          {/* Input */}
          <div className="flex items-center gap-2 px-4 py-3 bg-gray-800 border-t border-gray-700">
            <span className="text-green-400 font-mono text-sm shrink-0">$</span>
            <input
              ref={inputRef}
              type="text"
              value={cmd}
              onChange={(e) => setCmd(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={sendCmd.isPending}
              placeholder="Enter command…"
              className="flex-1 bg-transparent text-gray-100 font-mono text-sm outline-hidden placeholder-gray-600 disabled:opacity-50"
              autoComplete="off"
              spellCheck={false}
            />
            <button
              onClick={() =>
                cmd.trim() && sendCmd.mutate({ sessionId: session.sessionId, command: cmd.trim() })
              }
              disabled={!cmd.trim() || sendCmd.isPending}
              className="p-1.5 text-gray-400 hover:text-green-400 disabled:opacity-30 transition"
            >
              <Send size={14} />
            </button>
          </div>

          {/* Footer */}
          <div className="flex items-center gap-4 px-4 py-1.5 bg-gray-950 border-t border-gray-800 text-xs text-gray-600">
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-gray-500 inline-block" /> stdout
            </span>
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-red-500 inline-block" /> stderr
            </span>
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-gray-600 inline-block" /> system
            </span>
            <span className="ml-auto">Auto-refresh every 2s while connected — all commands audit-logged</span>
          </div>
        </div>
      )}
    </div>
  );
}
