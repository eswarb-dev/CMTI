import React, { useRef, useEffect } from 'react';
import { useChat } from '../../context/useChat';
import { useAuth } from '../../context/AuthContext';
import MessageItem from './MessageItem';
import InputBar from './InputBar';
import ChaoticOrbitLoader from './ChaoticOrbitLoader';
import { Cpu, AlertTriangle, Menu, Sparkles } from 'lucide-react';

const EXAMPLE_PROMPTS = [
  'What are the recommended steps for spindle vibration?',
  'Why did CNC-05 show repeated spindle alarms?',
  'Show the quality failures for SHAFT-A.',
  'What is the lockout/tagout procedure before maintenance?',
];

export const ChatPanel: React.FC = () => {
  const {
    messages,
    transportState,
    errorMessage,
    sendMessage,
    setIsMobileSidebarOpen,
  } = useChat();
  const { authenticated, openAuthDialog } = useAuth();

  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, transportState]);

  return (
    <div className="flex-1 flex flex-col h-full bg-transparent relative overflow-hidden">
      {/* Mobile Top Navigation */}
      <div className="lg:hidden flex items-center justify-between px-4 py-2 bg-brand-surface border-b border-brand-border">
        <button
          type="button"
          onClick={() => setIsMobileSidebarOpen(true)}
          className="p-1.5 rounded-xl text-brand-textMuted hover:text-brand-dark hover:bg-brand-cardHover transition-colors"
          title="Open Navigation"
        >
          <Menu className="w-5 h-5" />
        </button>
        <span className="text-sm font-semibold text-brand-text">ManufacturaIQ</span>
        <div className="w-9" aria-hidden="true" />
      </div>

      {/* Main message feed area */}
      <div className="flex-1 overflow-y-auto">
        {messages.length === 0 ? (
          /* Empty State */
          <div className="flex-1 flex flex-col items-center justify-center px-4 py-12 max-w-2xl mx-auto text-center">
            <div className="w-16 h-16 rounded-2xl bg-brand-surface border border-brand-border text-brand-dark flex items-center justify-center shadow-card mb-6">
              <Cpu className="w-8 h-8" />
            </div>
            <h1 className="text-2xl font-bold text-brand-text tracking-tight mb-2">
              Ask an engineering question.
            </h1>
            <p className="text-sm text-brand-textMuted max-w-md mb-8 leading-relaxed">
              Search manufacturing documents, maintenance procedures, production records and quality evidence using natural language.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-lg">
              {EXAMPLE_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  onClick={() => sendMessage(prompt)}
                  className="text-left p-4 rounded-xl bg-brand-surface border border-brand-border hover:border-brand-accent/30 hover:shadow-card transition-all text-sm text-brand-textMuted hover:text-brand-text"
                >
                  <Sparkles className="w-4 h-4 text-brand-accentText mb-2" />
                  <span className="leading-snug">{prompt}</span>
                </button>
              ))}
            </div>
            {!authenticated && (
              <div className="mt-6 w-full max-w-lg rounded-lg border border-brand-border bg-brand-surface px-3 py-2 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 text-left">
                <div>
                  <p className="text-xs font-semibold text-brand-text">Using Guest mode</p>
                  <p className="text-[11px] text-brand-textMuted">
                    Sign in or create a local account to keep a persistent profile on this prototype.
                  </p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    type="button"
                    onClick={() => openAuthDialog('sign-in')}
                    className="px-2.5 py-1.5 rounded-lg border border-brand-border bg-brand-card text-[11px] font-semibold text-brand-text hover:bg-brand-cardHover transition-colors"
                  >
                    Sign In
                  </button>
                  <button
                    type="button"
                    onClick={() => openAuthDialog('create-account')}
                    className="px-2.5 py-1.5 rounded-lg bg-brand-dark text-[11px] font-semibold text-white hover:bg-brand-accentText transition-colors"
                  >
                    Create Account
                  </button>
                </div>
              </div>
            )}
          </div>
        ) : (
          /* Messages */
          <div className="max-w-3xl mx-auto px-4 md:px-6 py-6 space-y-6">
            {messages.map((msg) => (
              <MessageItem key={msg.id} message={msg} />
            ))}

            {/* Submitting / Loading Indicator */}
            {transportState === 'submitting' && (
              <div className="flex items-start gap-3 my-4 animate-fadeIn">
                <div className="w-9 h-9 rounded-xl bg-brand-cardSubtle border border-brand-border text-brand-dark p-1.5 flex items-center justify-center shrink-0 shadow-sm mt-1">
                  <Cpu className="w-5 h-5 text-brand-dark animate-pulse" />
                </div>
                <div className="bg-brand-surface border border-brand-border rounded-2xl p-5 shadow-card max-w-md">
                  <div className="flex flex-col items-center justify-center py-2 space-y-4">
                    <ChaoticOrbitLoader />
                    <p className="text-xs font-medium text-brand-textMuted text-center">
                      Searching indexed manuals &amp; generating grounded answer...
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* Error Banner */}
            {transportState === 'error' && errorMessage && (
              <div className="flex items-center gap-3 p-4 rounded-xl bg-brand-error/10 border border-brand-error/20 text-brand-error text-xs shadow-card">
                <AlertTriangle className="w-4 h-4 shrink-0" />
                <div className="flex-1">
                  <span className="font-semibold">Query execution error: </span>
                  <span>{errorMessage}</span>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input Bar */}
      <InputBar />
    </div>
  );
};

export default ChatPanel;
