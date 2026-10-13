/* oxlint-disable react/only-export-components */
import React, { useEffect, useState } from 'react';
import { Cpu, LogIn, UserPlus, X } from 'lucide-react';
import { isBackendUnreachable, useAuth } from '../../context/AuthContext';
import type { RegisterRole } from '../../types/contracts';

export const REGISTER_ROLES: RegisterRole[] = [
  'Manufacturing Engineer',
  'Quality Engineer',
  'Maintenance Engineer',
  'Production Engineer',
  'Engineer',
  'Student / Researcher',
];

const AuthDialog: React.FC = () => {
  const { authDialogMode, closeAuthDialog } = useAuth();

  useEffect(() => {
    if (!authDialogMode) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeAuthDialog();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [authDialogMode, closeAuthDialog]);

  if (!authDialogMode) return null;

  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-[100] animate-fadeIn" onClick={closeAuthDialog} />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="auth-dialog-title"
        className="fixed inset-0 z-[110] flex items-center justify-center p-4 pointer-events-none"
      >
        <div className="w-full max-w-md rounded-lg border border-brand-border bg-brand-surface shadow-drawer p-5 pointer-events-auto">
          <div className="flex items-start justify-between gap-4 mb-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-brand-card border border-brand-border flex items-center justify-center">
                <Cpu className="w-5 h-5 text-brand-dark" />
              </div>
              <div>
                <h2 id="auth-dialog-title" className="text-base font-bold text-brand-text">
                  {authDialogMode === 'create-account' ? 'Create local account' : 'Sign in'}
                </h2>
                <p className="text-xs text-brand-textMuted">
                  {authDialogMode === 'create-account'
                    ? 'Accounts are stored locally on this ManufacturaIQ installation.'
                    : 'Sign in to use your local profile.'}
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={closeAuthDialog}
              className="p-1.5 text-brand-textMuted hover:text-brand-dark hover:bg-brand-cardHover rounded-lg transition-colors"
              title="Close"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {authDialogMode === 'create-account' ? <CreateAccountForm /> : <SignInForm />}
        </div>
      </div>
    </>
  );
};

const SignInForm: React.FC = () => {
  const { login, openAuthDialog, closeAuthDialog } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(username, password);
    } catch (err) {
      setError(
        isBackendUnreachable(err)
          ? 'Backend is unreachable. Check that the ManufacturaIQ API is running.'
          : 'Invalid username or password.',
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <TextField label="Username" value={username} onChange={setUsername} autoComplete="username" />
      <TextField label="Password" value={password} onChange={setPassword} type="password" autoComplete="current-password" />
      {error && <ErrorMessage text={error} />}
      <div className="flex flex-col gap-2">
        <button
          type="submit"
          disabled={submitting || !username.trim() || !password}
          className="w-full flex items-center justify-center gap-2 rounded-lg bg-brand-dark px-3 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-brand-accentText disabled:opacity-50"
        >
          <LogIn className="w-4 h-4" />
          <span>{submitting ? 'Signing In...' : 'Sign In'}</span>
        </button>
        <button
          type="button"
          onClick={() => openAuthDialog('create-account')}
          className="text-xs font-semibold text-brand-accentText hover:text-brand-dark"
        >
          Don't have an account? Create account
        </button>
        <button type="button" onClick={closeAuthDialog} className="text-xs text-brand-textMuted hover:text-brand-dark">
          Cancel
        </button>
      </div>
    </form>
  );
};

const CreateAccountForm: React.FC = () => {
  const { register, openAuthDialog, closeAuthDialog } = useAuth();
  const [displayName, setDisplayName] = useState('');
  const [username, setUsername] = useState('');
  const [role, setRole] = useState<RegisterRole>('Manufacturing Engineer');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    if (password !== confirmPassword) {
      setError('Password confirmation does not match.');
      return;
    }
    setSubmitting(true);
    try {
      await register({
        username,
        display_name: displayName,
        role,
        password,
      });
    } catch (err) {
      setError(
        isBackendUnreachable(err)
          ? 'Backend is unreachable. Check that the ManufacturaIQ API is running.'
          : err instanceof Error && err.message === 'That username is already in use.'
            ? 'That username is already in use.'
            : 'Account could not be created. Check the fields and try again.',
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <TextField label="Display name" value={displayName} onChange={setDisplayName} autoComplete="name" />
      <TextField label="Username" value={username} onChange={setUsername} autoComplete="username" />
      <label className="block space-y-1.5">
        <span className="text-xs font-semibold text-brand-text">Role</span>
        <select
          value={role}
          onChange={(event) => setRole(event.target.value as RegisterRole)}
          className="w-full rounded-lg border border-brand-border bg-brand-card px-3 py-2 text-sm outline-none focus:border-brand-accent"
        >
          {REGISTER_ROLES.map((item) => (
            <option key={item} value={item}>{item}</option>
          ))}
        </select>
      </label>
      <TextField label="Password" value={password} onChange={setPassword} type="password" autoComplete="new-password" />
      <TextField label="Confirm password" value={confirmPassword} onChange={setConfirmPassword} type="password" autoComplete="new-password" />
      {error && <ErrorMessage text={error} />}
      <div className="flex flex-col gap-2">
        <button
          type="submit"
          disabled={submitting || !displayName.trim() || !username.trim() || password.length < 8 || !confirmPassword}
          className="w-full flex items-center justify-center gap-2 rounded-lg bg-brand-dark px-3 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-brand-accentText disabled:opacity-50"
        >
          <UserPlus className="w-4 h-4" />
          <span>{submitting ? 'Creating...' : 'Create Account'}</span>
        </button>
        <button
          type="button"
          onClick={() => openAuthDialog('sign-in')}
          className="text-xs font-semibold text-brand-accentText hover:text-brand-dark"
        >
          Already have an account? Sign In
        </button>
        <button type="button" onClick={closeAuthDialog} className="text-xs text-brand-textMuted hover:text-brand-dark">
          Cancel
        </button>
      </div>
    </form>
  );
};

interface TextFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  autoComplete?: string;
}

const TextField: React.FC<TextFieldProps> = ({ label, value, onChange, type = 'text', autoComplete }) => (
  <label className="block space-y-1.5">
    <span className="text-xs font-semibold text-brand-text">{label}</span>
    <input
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="w-full rounded-lg border border-brand-border bg-brand-card px-3 py-2 text-sm outline-none focus:border-brand-accent"
      type={type}
      autoComplete={autoComplete}
    />
  </label>
);

const ErrorMessage: React.FC<{ text: string }> = ({ text }) => (
  <div className="rounded-lg border border-brand-error/20 bg-brand-error/10 px-3 py-2 text-xs text-brand-error">
    {text}
  </div>
);

export default AuthDialog;
