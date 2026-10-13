import React, { useState } from 'react';
import { Paperclip, Send, X, FileText, Mic } from 'lucide-react';
import { useChat } from '../../context/useChat';
import ChaoticOrbitLoader from './ChaoticOrbitLoader';

export const InputBar: React.FC = () => {
  const {
    sendMessage,
    transportState,
    sessionAttachment,
    removeSessionFile,
    setUploadModalOpen,
  } = useChat();

  const [inputVal, setInputVal] = useState('');

  const isSubmitting = transportState === 'submitting';
  const isUploading = transportState === 'uploading';
  const canSend = (inputVal.trim().length > 0 || sessionAttachment !== null) && !isSubmitting;

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleSend = () => {
    if (!canSend) return;
    sendMessage(inputVal);
    setInputVal('');
  };

  return (
    <div className="p-4 bg-transparent">
      <div className="max-w-3xl mx-auto space-y-2">
        {/* Temporary session-attached PDF chip */}
        {sessionAttachment && (
          <div className="inline-flex items-center gap-2 bg-brand-surface border border-brand-border text-brand-text text-xs px-3 py-1.5 rounded-xl shadow-sm animate-fadeIn">
            <FileText className="w-3.5 h-3.5 text-brand-accentText" />
            <span className="font-medium truncate max-w-xs">{sessionAttachment.name}</span>
            <span className="text-[11px] text-brand-textSubtle">
              ({(sessionAttachment.size / (1024 * 1024)).toFixed(1)} MB)
            </span>
            <span className="text-[10px] bg-brand-accentLight text-brand-accentText px-1.5 py-0.5 rounded font-medium">
              Session only
            </span>
            <button
              type="button"
              onClick={removeSessionFile}
              className="p-0.5 hover:bg-brand-cardHover rounded text-brand-textSubtle hover:text-brand-text transition-colors"
              title="Remove temporary attachment"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {/* Solid neutral pill input — Send button is the single yellow CTA */}
        <div className="flex items-center gap-2 bg-brand-surface border border-brand-border hover:border-brand-accent/40 rounded-full px-4 py-2.5 shadow-input transition-all focus-within:border-brand-accent focus-within:shadow-inputFocus">
          {/* Attach button */}
          <button
            type="button"
            onClick={() => setUploadModalOpen(true)}
            disabled={isUploading || isSubmitting}
            title="PDF ingestion is not connected yet"
            className="p-2 text-brand-textSubtle hover:text-brand-dark hover:bg-brand-cardHover rounded-full transition-colors shrink-0 disabled:opacity-50"
          >
            {isUploading ? (
              <ChaoticOrbitLoader size={20} />
            ) : (
              <Paperclip className="w-5 h-5" />
            )}
          </button>

          {/* Textarea */}
          <textarea
            value={inputVal}
            onChange={(e) => setInputVal(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask a manufacturing engineering question..."
            rows={1}
            disabled={isSubmitting}
            className="flex-1 bg-transparent text-brand-text placeholder-brand-textSubtle text-sm resize-none focus:outline-none py-1 max-h-32 min-h-[24px]"
          />

          {/* Microphone (visual only) */}
          <button
            type="button"
            className="p-2 text-brand-textSubtle hover:text-brand-dark hover:bg-brand-cardHover rounded-full transition-colors shrink-0"
            title="Voice input (coming soon)"
          >
            <Mic className="w-5 h-5" />
          </button>

          {/* Send button — the single yellow-filled CTA */}
          <button
            type="button"
            onClick={handleSend}
            disabled={!canSend}
            title="Send query (Enter)"
            className={`w-9 h-9 rounded-full flex items-center justify-center shrink-0 transition-all ${
              canSend
                ? 'bg-brand-accent hover:bg-brand-accentHover text-brand-dark shadow-sm cursor-pointer active:scale-95'
                : 'bg-brand-cardSubtle text-brand-textSubtle cursor-not-allowed'
            }`}
          >
            {isSubmitting ? (
              <ChaoticOrbitLoader size={16} />
            ) : (
              <Send className="w-4 h-4 -rotate-12 translate-x-[-1px] translate-y-[-1px]" />
            )}
          </button>
        </div>

        {/* Hint */}
        <div className="flex items-center justify-center gap-2 text-[11px] text-brand-textSubtle px-2">
          <span>Evidence-grounded engineering assistance</span>
          <span>•</span>
          <span>Press Enter to send, Shift+Enter for newline</span>
        </div>
      </div>
    </div>
  );
};

export default InputBar;
