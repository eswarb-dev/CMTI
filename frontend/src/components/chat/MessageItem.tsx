import React, { useState } from 'react';
import type { ChatMessage } from '../../types/contracts';
import CitationBadge from './CitationBadge';
import HumanReviewBanner from './HumanReviewBanner';
import {
  FileText,
  ChevronDown,
  ChevronUp,
  Cpu,
  Layers,
  Wrench,
  CheckCircle2,
  ThumbsUp,
  ThumbsDown,
  Copy,
  RefreshCw,
  Pencil,
  ShieldCheck,
  ShieldAlert,
  HelpCircle,
} from 'lucide-react';
import { useOptionalAuth } from '../../context/AuthContext';
import { initialsFromDisplayName } from '../../context/authUtils';

const StatusBadge: React.FC<{ status?: string }> = ({ status }) => {
  if (status === 'pass') {
    return (
      <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-brand-success/10 border border-brand-success/20 text-brand-success text-[11px] font-medium">
        <ShieldCheck className="w-3.5 h-3.5" />
        <span>Evidence Checked</span>
      </div>
    );
  }
  if (status === 'human_review') {
    return (
      <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-brand-warning/10 border border-brand-warning/20 text-brand-warning text-[11px] font-medium">
        <ShieldAlert className="w-3.5 h-3.5" />
        <span>Human Review Recommended</span>
      </div>
    );
  }
  if (status === 'needs_clarification') {
    return (
      <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-brand-accentLight border border-brand-accent/20 text-brand-accentText text-[11px] font-medium">
        <HelpCircle className="w-3.5 h-3.5" />
        <span>Additional Information Required</span>
      </div>
    );
  }
  return null;
};

interface MessageItemProps {
  message: ChatMessage;
}

export const MessageItem: React.FC<MessageItemProps> = ({ message }) => {
  const auth = useOptionalAuth();
  const [showEvidence, setShowEvidence] = useState(false);
  const [showCauses, setShowCauses] = useState(false);
  const [showChecks, setShowChecks] = useState(false);
  const [feedback, setFeedback] = useState<'like' | 'dislike' | null>(null);

  const isUser = message.sender === 'user';

  // TODO: Stub handler — need backend wiring for regenerate
  const handleRegenerate = () => {
    console.log('[TODO] Regenerate response for message:', message.id);
  };

  // TODO: Stub handler — need backend wiring for like/dislike
  const handleFeedback = (type: 'like' | 'dislike') => {
    console.log('[TODO] Feedback:', type, 'for message:', message.id);
    setFeedback(type);
  };

  // Copy is fully functional
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(message.text);
    } catch {
      const textarea = document.createElement('textarea');
      textarea.value = message.text;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
    }
  };

  // Helper to render text with interactive [1], [2] citation badges
  const renderTextWithCitations = (text: string) => {
    const parts = text.split(/(\[\d+\])/g);

    return parts.map((part, index) => {
      const citationMatch = part.match(/^\[(\d+)\]$/);
      if (citationMatch) {
        const citationNumber = parseInt(citationMatch[1], 10);
        return <CitationBadge key={index} citationNumber={citationNumber} />;
      }
      return <span key={index}>{part}</span>;
    });
  };

  // Helper to render parsed numbered steps
  const renderAssistantContent = (text: string) => {
    const lines = text.split('\n');
    const introLines: string[] = [];
    const stepItems: { number: number; title: string; body: string; citations: number[] }[] = [];
    const outroLines: string[] = [];

    let parsingSteps = false;
    let currentStep: { number: number; title: string; body: string; citations: number[] } | null = null;

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trim();
      const stepMatch = line.match(/^(\d+)\.\s+\*\*(.*?)\*\*(.*)$/);

      if (stepMatch) {
        parsingSteps = true;
        if (currentStep) {
          stepItems.push(currentStep);
        }
        const stepNum = parseInt(stepMatch[1], 10);
        const title = stepMatch[2];
        const rest = stepMatch[3];
        currentStep = {
          number: stepNum,
          title,
          body: rest,
          citations: [],
        };
      } else if (parsingSteps && currentStep) {
        if (line === '') {
          continue;
        } else if (line.match(/^If\s/i) || line.match(/^Note:/i) || line.match(/^Conclusion:/i)) {
          stepItems.push(currentStep);
          currentStep = null;
          parsingSteps = false;
          outroLines.push(line);
        } else {
          currentStep.body += (currentStep.body ? ' ' : '') + line;
        }
      } else if (!parsingSteps) {
        introLines.push(line);
      }
    }

    if (currentStep) {
      stepItems.push(currentStep);
    }

    if (stepItems.length === 0) {
      return (
        <div className="space-y-3 leading-relaxed text-brand-textMuted">
          {lines.map((l, idx) => (
            <p key={idx}>{renderTextWithCitations(l)}</p>
          ))}
        </div>
      );
    }

    return (
      <div className="space-y-4">
        {introLines.length > 0 && (
          <p className="text-brand-text leading-relaxed font-normal">
            {renderTextWithCitations(introLines.join(' '))}
          </p>
        )}

        <div className="space-y-3 my-2">
          {stepItems.map((step) => (
            <div
              key={step.number}
              className="flex items-start gap-3 p-3.5 rounded-xl bg-brand-cardSubtle border border-brand-border"
            >
              <div className="w-6 h-6 rounded-full bg-brand-accent text-brand-dark font-semibold text-xs flex items-center justify-center shrink-0 mt-0.5">
                {step.number}
              </div>
              <div className="flex-1 min-w-0">
                <h4 className="text-sm font-semibold text-brand-text">
                  {step.title}
                </h4>
                <p className="mt-1 text-sm text-brand-textMuted leading-relaxed">
                  {renderTextWithCitations(step.body)}
                </p>
              </div>
            </div>
          ))}
        </div>

        {outroLines.length > 0 && (
          <p className="text-sm text-brand-textMuted leading-relaxed pt-1">
            {renderTextWithCitations(outroLines.join(' '))}
          </p>
        )}
      </div>
    );
  };


  if (isUser) {
    return (
      <div className="flex items-start justify-end gap-3 my-4">
        <div className="max-w-2xl">
          <div className="bg-brand-card border border-brand-border text-brand-dark rounded-2xl rounded-tr-md px-4 py-3 shadow-sm">
            <p className="text-sm font-normal leading-relaxed">
              {message.text}
            </p>
          </div>
          {message.attachmentName && (
            <div className="mt-2 inline-flex items-center gap-1.5 text-xs text-brand-accentText bg-brand-accentLight border border-brand-accent/20 px-2.5 py-1 rounded-lg">
              <FileText className="w-3.5 h-3.5" />
              <span>Attached: {message.attachmentName}</span>
            </div>
          )}
        </div>
        <div className="w-8 h-8 rounded-full bg-brand-card border border-brand-border text-brand-dark font-semibold text-xs flex items-center justify-center shrink-0 mt-1 shadow-sm">
          {initialsFromDisplayName(auth?.user?.display_name ?? '')}
        </div>
      </div>
    );
  }

  const hasEvidence = message.evidenceBundle && message.evidenceBundle.length > 0;
  const hasCauses = message.reasoning?.possible_causes && message.reasoning.possible_causes.length > 0;
  const hasChecks = message.reasoning?.recommended_checks && message.reasoning.recommended_checks.length > 0;

  return (
    <div className="flex items-start gap-3 my-5 group/msg">
      <div className="w-9 h-9 rounded-xl bg-brand-cardSubtle border border-brand-border text-brand-dark p-1.5 flex items-center justify-center shrink-0 shadow-sm mt-1">
        <Cpu className="w-5 h-5 text-brand-dark" />
      </div>

      <div className="flex-1 min-w-0">
        {/* Header */}
        <div className="flex items-center justify-between gap-2 mb-2">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-brand-text text-sm tracking-wide">
              ManufacturaIQ
            </span>
            <StatusBadge status={message.status} />
          </div>
          <div className="flex items-center gap-1">
            <span className="text-xs text-brand-textSubtle">{message.timestamp}</span>
            <div className="hidden group-hover/msg:flex items-center gap-0.5 ml-1">
              <button
                type="button"
                onClick={handleRegenerate}
                className="p-1 text-brand-textSubtle hover:text-brand-accentText rounded-md hover:bg-brand-cardHover transition-colors"
                title="Regenerate response"
              >
                <RefreshCw className="w-3.5 h-3.5" />
              </button>
              <button
                type="button"
                className="p-1 text-brand-textSubtle hover:text-brand-accentText rounded-md hover:bg-brand-cardHover transition-colors"
                title="Edit response"
              >
                <Pencil className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>

        {message.status === 'human_review' && (
          <HumanReviewBanner reasons={message.reviewReasons} />
        )}

        <div className="text-sm">
          {renderAssistantContent(message.text)}
        </div>

        {/* Expandable sections */}
        {(hasChecks || hasCauses || hasEvidence) && (
          <div className="mt-4 pt-3 border-t border-brand-borderLight space-y-2">
            {hasChecks && (
              <div className="border border-brand-border rounded-xl overflow-hidden bg-brand-cardSubtle">
                <button
                  type="button"
                  onClick={() => setShowChecks(!showChecks)}
                  className="w-full flex items-center justify-between px-3.5 py-2.5 text-xs font-medium text-brand-text hover:bg-brand-cardHover transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4 text-brand-success" />
                    <span>Recommended checks ({message.reasoning?.recommended_checks?.length})</span>
                  </div>
                  {showChecks ? <ChevronUp className="w-4 h-4 text-brand-textSubtle" /> : <ChevronDown className="w-4 h-4 text-brand-textSubtle" />}
                </button>
                {showChecks && (
                  <div className="px-3.5 pb-3 pt-1 border-t border-brand-borderLight text-xs text-brand-textMuted space-y-1.5">
                    {message.reasoning?.recommended_checks?.map((chk, i) => (
                      <div key={i} className="flex items-start gap-2">
                        <span className="text-brand-accentText font-semibold">•</span>
                        <span>{chk}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {hasCauses && (
              <div className="border border-brand-border rounded-xl overflow-hidden bg-brand-cardSubtle">
                <button
                  type="button"
                  onClick={() => setShowCauses(!showCauses)}
                  className="w-full flex items-center justify-between px-3.5 py-2.5 text-xs font-medium text-brand-text hover:bg-brand-cardHover transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <Wrench className="w-4 h-4 text-brand-warning" />
                    <span>Possible causes ({message.reasoning?.possible_causes?.length})</span>
                  </div>
                  {showCauses ? <ChevronUp className="w-4 h-4 text-brand-textSubtle" /> : <ChevronDown className="w-4 h-4 text-brand-textSubtle" />}
                </button>
                {showCauses && (
                  <div className="px-3.5 pb-3 pt-1 border-t border-brand-borderLight text-xs text-brand-textMuted space-y-1.5">
                    {message.reasoning?.possible_causes?.map((cause, i) => (
                      <div key={i} className="flex items-start gap-2">
                        <span className="text-brand-warning font-semibold">•</span>
                        <span>{cause}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {hasEvidence && (
              <div className="border border-brand-border rounded-xl overflow-hidden bg-brand-cardSubtle">
                <button
                  type="button"
                  onClick={() => setShowEvidence(!showEvidence)}
                  className="w-full flex items-center justify-between px-3.5 py-2.5 text-xs font-medium text-brand-text hover:bg-brand-cardHover transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <Layers className="w-4 h-4 text-brand-accentText" />
                    <span>Retrieved Evidence ({message.evidenceBundle?.length})</span>
                  </div>
                  {showEvidence ? <ChevronUp className="w-4 h-4 text-brand-textSubtle" /> : <ChevronDown className="w-4 h-4 text-brand-textSubtle" />}
                </button>
                {showEvidence && (
                  <div className="px-3.5 pb-3 pt-2 border-t border-brand-borderLight text-xs text-brand-textMuted space-y-2">
                    {message.evidenceBundle?.map((ev, i) => (
                      <div key={i} className="p-2.5 rounded-lg bg-brand-card border border-brand-border text-brand-textMuted shadow-sm">
                        <div className="flex items-center justify-between text-[11px] text-brand-textSubtle mb-1">
                          <span className="font-mono text-brand-accentText font-semibold">{ev.evidence_id}</span>
                          <span className="text-brand-textSubtle">
                            {ev.provenance.document_id || ev.provenance.source_id}
                            {ev.provenance.page_start ? ` (p. ${ev.provenance.page_start})` : ''}
                          </span>
                        </div>
                        <p className="text-brand-text text-xs mt-1">{ev.content}</p>
                        {ev.retrieval_score !== null && (
                          <p className="mt-1 text-[11px] text-brand-textSubtle">
                            Retrieval similarity: {ev.retrieval_score.toFixed(3)}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Per-message action row */}
        <div className="mt-3 pt-2 border-t border-brand-borderLight flex items-center gap-1">
          <button
            type="button"
            onClick={() => handleFeedback('like')}
            className={`inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-medium transition-colors ${
              feedback === 'like'
                ? 'bg-brand-success/10 text-brand-success'
                : 'text-brand-textSubtle hover:text-brand-success hover:bg-brand-success/10'
            }`}
            title="Good response"
          >
            <ThumbsUp className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={() => handleFeedback('dislike')}
            className={`inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-medium transition-colors ${
              feedback === 'dislike'
                ? 'bg-brand-error/10 text-brand-error'
                : 'text-brand-textSubtle hover:text-brand-error hover:bg-brand-error/10'
            }`}
            title="Bad response"
          >
            <ThumbsDown className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={handleCopy}
            className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-medium text-brand-textSubtle hover:text-brand-accentText hover:bg-brand-accentLight transition-colors"
            title="Copy response"
          >
            <Copy className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={handleRegenerate}
            className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-medium text-brand-textSubtle hover:text-brand-accentText hover:bg-brand-accentLight transition-colors"
            title="Regenerate response"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
};

export default MessageItem;
