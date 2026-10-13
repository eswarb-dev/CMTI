import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, Cpu } from 'lucide-react';

export const NotFoundPage: React.FC = () => {
  return (
    <div className="flex-1 flex flex-col h-full bg-transparent overflow-y-auto">
      <div className="p-6 md:p-8 max-w-2xl w-full mx-auto space-y-6 flex-1 flex flex-col items-center justify-center text-center">
        <div className="w-16 h-16 rounded-2xl bg-brand-surface border border-brand-border text-brand-dark flex items-center justify-center shadow-card">
          <Cpu className="w-8 h-8" />
        </div>
        <div className="space-y-2">
          <h1 className="text-3xl font-bold text-brand-text tracking-tight">404</h1>
          <p className="text-sm text-brand-textMuted max-w-md mx-auto">
            The page you're looking for doesn't exist or has been moved.
          </p>
        </div>
        <Link
          to="/"
          className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-brand-accent hover:bg-brand-accentHover text-brand-dark font-medium text-sm shadow-sm transition-all active:scale-[0.98]"
        >
          <ArrowLeft className="w-4 h-4" />
          <span>Back to Copilot Chat</span>
        </Link>
      </div>
    </div>
  );
};

export default NotFoundPage;
