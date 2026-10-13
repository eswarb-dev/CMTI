import React, { useEffect, useRef } from 'react';
import { useChat } from '../../context/useChat';

interface CitationBadgeProps {
  citationNumber: number;
}

export const CitationBadge: React.FC<CitationBadgeProps> = ({ citationNumber }) => {
  const { selectedCitationNumber, setSelectedCitation, activeCitations } = useChat();
  const isSelected = selectedCitationNumber === citationNumber;
  const citation = activeCitations.find((c) => c.citation_number === citationNumber);
  const wrapperRef = useRef<HTMLSpanElement>(null);

  // Close the popover on click-away or Escape
  useEffect(() => {
    if (!isSelected) return;
    const onDown = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setSelectedCitation(null);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelectedCitation(null);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [isSelected, setSelectedCitation]);

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedCitation(isSelected ? null : citationNumber);
  };

  return (
    <span className="relative inline-block" ref={wrapperRef}>
      <button
        type="button"
        onClick={handleClick}
        title={`View source [${citationNumber}]`}
        className={`inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 text-xs font-semibold rounded-md transition-all duration-150 select-none mx-0.5 cursor-pointer ${
          isSelected
            ? 'bg-brand-accent text-brand-dark shadow-sm scale-105'
            : 'bg-brand-accentLight hover:bg-brand-accent/20 text-brand-accentText border border-brand-accent/20'
        }`}
      >
        {citationNumber}
      </button>
      {isSelected && citation && (
        <span className="absolute left-1/2 -translate-x-1/2 top-full mt-2 z-50 block w-64 max-w-[80vw] p-3 rounded-xl bg-brand-surface border border-brand-border shadow-card text-left">
          <span className="flex items-center justify-between gap-1">
            <span className="text-xs font-semibold text-brand-text truncate">
              {citation.document_title}
            </span>
            {citation.page_number && (
              <span className="text-[11px] font-semibold text-brand-accentText bg-brand-accentLight px-1.5 py-0.5 rounded shrink-0">
                Page {citation.page_number}
              </span>
            )}
          </span>
          <span className="mt-1.5 block text-xs text-brand-textMuted leading-relaxed line-clamp-4">
            {citation.snippet}
          </span>
          <span className="mt-2 pt-2 border-t border-brand-borderLight flex items-center justify-between text-[11px]">
            <span className="font-mono text-brand-accentText font-semibold">
              {citation.label ? `Citation ${citation.label}` : `Citation [${citation.citation_number}]`}
            </span>
            {citation.section && (
              <span className="truncate max-w-[140px] text-brand-textSubtle text-[10px]">
                {citation.section}
              </span>
            )}
          </span>
        </span>
      )}
    </span>
  );
};

export default CitationBadge;
