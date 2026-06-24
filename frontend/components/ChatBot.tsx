'use client';

import { useEffect, useRef, useState } from 'react';
import { MessageCircle, X, ArrowRight, Loader2 } from 'lucide-react';

interface Message {
  role: 'user' | 'assistant';
  content: string;
}

const SUGGESTED = [
  'What is TestPilot AI?',
  'How does model routing work?',
  'What does risk level mean?',
  'What is the self-repair agent?',
  'How are tests executed?',
];

function TypingIndicator() {
  return (
    <div className="flex gap-1.5 items-center px-4 py-3">
      {[0, 1, 2].map((i) => (
        <span key={i} className={`typing-dot w-1.5 h-1.5 rounded-full bg-[#475569]`} />
      ))}
    </div>
  );
}

export default function ChatBot({ jobContext }: { jobContext?: string }) {
  const [open, setOpen]         = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput]       = useState('');
  const [loading, setLoading]   = useState(false);
  const bottomRef               = useRef<HTMLDivElement | null>(null);
  const inputRef                = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [open]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  async function send(text: string) {
    if (!text.trim() || loading) return;
    const userMsg: Message = { role: 'user', content: text.trim() };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setLoading(true);
    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: [...messages, userMsg],
          jobContext,
        }),
      });
      const data = await res.json();
      if (data.message) {
        setMessages((prev) => [...prev, { role: 'assistant', content: data.message }]);
      }
    } catch {
      setMessages((prev) => [...prev, { role: 'assistant', content: 'Connection failed. Please try again.' }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      {/* Floating button */}
      <button
        onClick={() => setOpen(true)}
        aria-label="Open assistant"
        className="fixed bottom-6 right-6 z-50 w-14 h-14 rounded-full bg-[#0d0d14] border border-[#00d4ff]/50 text-[#00d4ff] flex items-center justify-center hover:border-[#00d4ff] hover:shadow-lg hover:shadow-[#00d4ff]/20 transition-all"
        style={{ display: open ? 'none' : 'flex' }}
      >
        <MessageCircle className="w-6 h-6" />
      </button>

      {/* Drawer */}
      <div className={`chat-drawer fixed right-0 top-0 h-full z-50 flex flex-col ${open ? 'open' : 'closed'}`}
        style={{ width: 'min(380px, 100vw)', background: '#0d0d14', borderLeft: '1px solid #1a1a2e', boxShadow: '-4px 0 24px rgba(0,0,0,0.5)' }}>

        {/* Header */}
        <div className="flex items-start justify-between px-5 py-4 border-b border-[#1a1a2e] flex-shrink-0">
          <div>
            <div className="text-[#f1f5f9] font-semibold text-sm">TestPilot Assistant</div>
            <div className="text-[#475569] text-xs font-medium mt-0.5">Ask anything about the platform</div>
          </div>
          <button onClick={() => setOpen(false)}
            className="text-[#475569] hover:text-[#94a3b8] transition-colors p-1 -mr-1">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
          {messages.length === 0 ? (
            <div className="space-y-3">
              <p className="text-xs text-[#475569] font-semibold uppercase tracking-widest">Suggested questions</p>
              <div className="flex flex-col gap-2">
                {SUGGESTED.map((q) => (
                  <button key={q} onClick={() => send(q)}
                    className="text-left px-3 py-2.5 border border-[#1a1a2e] rounded-lg text-[#94a3b8] text-sm font-medium hover:border-[#00d4ff]/50 hover:text-[#00d4ff] transition-colors">
                    {q}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((msg, i) => (
              <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[85%] px-4 py-3 text-sm font-medium leading-relaxed ${
                  msg.role === 'user'
                    ? 'bg-[#00d4ff]/10 border border-[#00d4ff]/20 text-[#f1f5f9] rounded-xl rounded-tr-sm'
                    : 'bg-[#0a0a12] border border-[#1a1a2e] text-[#e2e8f0] rounded-xl rounded-tl-sm'
                }`}>
                  {msg.content}
                </div>
              </div>
            ))
          )}
          {loading && (
            <div className="flex justify-start">
              <div className="bg-[#0a0a12] border border-[#1a1a2e] rounded-xl rounded-tl-sm">
                <TypingIndicator />
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="flex-shrink-0 border-t border-[#1a1a2e] px-4 py-3">
          <div className="flex gap-2">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input); } }}
              placeholder="Ask about TestPilot AI..."
              disabled={loading}
              className="flex-1 bg-[#050508] border border-[#1a1a2e] rounded-lg px-3 py-2.5 text-sm font-medium text-[#f1f5f9] placeholder:text-[#2a2a3e] focus:outline-none focus:border-[#00d4ff]/50 transition-colors disabled:opacity-50"
            />
            <button onClick={() => send(input)} disabled={loading || !input.trim()}
              className="w-10 h-10 rounded-lg bg-[#00d4ff] hover:bg-[#00b8d9] text-black flex items-center justify-center flex-shrink-0 disabled:opacity-40 transition-colors">
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <ArrowRight className="w-4 h-4" />}
            </button>
          </div>
        </div>
      </div>

      {/* Overlay */}
      {open && (
        <div className="fixed inset-0 z-40 bg-black/30 backdrop-blur-sm md:hidden"
          onClick={() => setOpen(false)} />
      )}
    </>
  );
}
