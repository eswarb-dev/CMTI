import React, { useState } from 'react';
import { ShieldAlert, ChevronDown, ChevronUp, AlertCircle } from 'lucide-react';

interface HumanReviewBannerProps {
  reasons?: string[];
}

export const HumanReviewBanner: React.FC<HumanReviewBannerProps> = ({ reasons = [] }) => {
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <div className="mb-3.5 rounded-xl border border-brand-warning/30 bg-brand-warning/10 px-3.5 py-2.5 text-brand-warning transition-all shadow-subtle">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-xs font-semibold text-brand-warning">
          <div className="w-5 h-5 rounded-md bg-brand-warning/15 border border-brand-warning/25 text-brand-warning flex items-center justify-center shrink-0">
            <ShieldAlert className="w-3.5 h-3.5" />
          </div>
          <span>Human review recommended</span>
          <span className="text-[11px] text-brand-warning/70 font-normal hidden sm:inline">
            — Verify with lead engineer prior to operational action
          </span>
        </div>
        {reasons.length > 0 && (
          <button
            type="button"
            onClick={() => setIsExpanded(!isExpanded)}
            className="flex items-center gap-1 text-[11px] text-brand-warning/80 hover:text-brand-warning font-medium px-2 py-0.5 rounded-md hover:bg-brand-warning/10 transition-colors"
          >
            <span>{isExpanded ? 'Hide details' : 'View details'}</span>
            {isExpanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>
        )}
      </div>

      {isExpanded && reasons.length > 0 && (
        <div className="mt-2.5 pt-2 border-t border-brand-warning/20 text-xs text-brand-warning/90 space-y-1.5">
          {reasons.map((reason, idx) => (
            <div key={idx} className="flex items-start gap-1.5">
              <AlertCircle className="w-3.5 h-3.5 text-brand-warning/70 shrink-0 mt-0.5" />
              <span>{reason}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default HumanReviewBanner;
