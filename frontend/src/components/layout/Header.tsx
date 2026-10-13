import React from 'react';
import { Link } from 'react-router-dom';
import { Cpu, Settings, Wifi, WifiOff } from 'lucide-react';
import { useChat } from '../../context/useChat';
import { useAuth } from '../../context/AuthContext';
import { initialsFromDisplayName } from '../../context/authUtils';

export const Header: React.FC = () => {
  const { setSettingsOpen, connectionStatus } = useChat();
  const { user, authenticated } = useAuth();
  const accountLabel = authenticated ? user?.display_name ?? 'Account' : 'Guest';
  const accountInitials = authenticated ? initialsFromDisplayName(user?.display_name ?? '') : 'G';

  return (
    <header className="h-14 bg-brand-surface border-b border-brand-border px-4 md:px-6 flex items-center justify-between shrink-0 select-none z-30">
      <div className="flex items-center gap-3">
        <Link to="/" className="flex items-center gap-2.5 group">
          <div className="w-8 h-8 rounded-xl bg-brand-cardSubtle border border-brand-border text-brand-dark flex items-center justify-center shadow-sm group-hover:scale-105 transition-transform">
            <Cpu className="w-4.5 h-4.5 text-brand-dark" />
          </div>
          <div className="flex flex-col">
            <span className="text-base font-bold text-brand-text tracking-tight leading-tight">
              Manufactura<span className="text-brand-accentText">IQ</span>
            </span>
            <span className="text-[10px] text-brand-textSubtle leading-tight hidden sm:block">
              Manufacturing Engineering Copilot
            </span>
          </div>
        </Link>
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setSettingsOpen(true)}
          className="hidden md:inline-flex items-center gap-2 px-2 py-1 rounded-full border border-brand-border bg-brand-cardSubtle text-xs font-semibold text-brand-text hover:bg-brand-cardHover transition-colors"
          title={authenticated ? 'Account settings' : 'Guest account options'}
        >
          <span className="w-6 h-6 rounded-full bg-brand-card border border-brand-border flex items-center justify-center text-[10px] text-brand-dark">
            {accountInitials}
          </span>
          <span className="max-w-32 truncate">{accountLabel}</span>
        </button>
        <div
          className={`hidden sm:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[11px] font-medium ${
            connectionStatus === 'online'
              ? 'bg-brand-success/10 border-brand-success/20 text-brand-success'
              : connectionStatus === 'checking'
                ? 'bg-brand-cardSubtle border-brand-border text-brand-textMuted'
                : 'bg-brand-error/10 border-brand-error/20 text-brand-error'
          }`}
          title="Backend process liveness"
        >
          {connectionStatus === 'online' ? (
            <Wifi className="w-3.5 h-3.5" />
          ) : (
            <WifiOff className="w-3.5 h-3.5" />
          )}
          <span>{connectionStatus === 'online' ? 'Online' : connectionStatus === 'checking' ? 'Checking' : 'Offline'}</span>
        </div>
        <button
          type="button"
          onClick={() => setSettingsOpen(true)}
          className="p-2 text-brand-textMuted hover:text-brand-dark hover:bg-brand-cardHover rounded-lg transition-colors"
          title="Settings"
        >
          <Settings className="w-4 h-4" />
        </button>
      </div>
    </header>
  );
};

export default Header;
