import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import AuthDialog from './AuthDialog';

const loginMock = vi.fn();
const registerMock = vi.fn();
const closeAuthDialogMock = vi.fn();
const openAuthDialogMock = vi.fn();
let mode: 'sign-in' | 'create-account' | null = 'sign-in';

vi.mock('../../context/AuthContext', () => ({
  useAuth: () => ({
    authDialogMode: mode,
    login: loginMock,
    register: registerMock,
    closeAuthDialog: closeAuthDialogMock,
    openAuthDialog: openAuthDialogMock,
  }),
  isBackendUnreachable: (error: unknown) =>
    error instanceof Error && error.message.includes('unreachable'),
}));

describe('AuthDialog', () => {
  beforeEach(() => {
    mode = 'sign-in';
    loginMock.mockReset();
    registerMock.mockReset();
    closeAuthDialogMock.mockReset();
    openAuthDialogMock.mockReset();
  });

  it('Sign In opens modal, submits, and can close back to guest', async () => {
    loginMock.mockResolvedValueOnce(undefined);
    render(<AuthDialog />);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/username/i), { target: { value: 'eswar' } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'private-pass' } });
    fireEvent.submit(screen.getByRole('button', { name: /^sign in$/i }).closest('form')!);
    await waitFor(() => expect(loginMock).toHaveBeenCalledWith('eswar', 'private-pass'));
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }));
    expect(closeAuthDialogMock).toHaveBeenCalled();
  });

  it('shows invalid login and backend unreachable messages safely', async () => {
    loginMock.mockRejectedValueOnce(new Error('Invalid username or password.'));
    render(<AuthDialog />);
    fireEvent.change(screen.getByLabelText(/username/i), { target: { value: 'eswar' } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'wrong' } });
    fireEvent.click(screen.getByRole('button', { name: /^sign in$/i }));
    expect(await screen.findByText('Invalid username or password.')).toBeInTheDocument();
  });

  it('switches from sign in to create account', () => {
    render(<AuthDialog />);
    fireEvent.click(screen.getByRole('button', { name: /create account/i }));
    expect(openAuthDialogMock).toHaveBeenCalledWith('create-account');
  });

  it('Create Account renders required fields and blocks confirmation mismatch', async () => {
    mode = 'create-account';
    render(<AuthDialog />);
    expect(screen.getByLabelText(/display name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^role$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^password$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/confirm password/i)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/display name/i), { target: { value: 'New User' } });
    fireEvent.change(screen.getByLabelText(/username/i), { target: { value: 'new-user' } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: 'private-pass' } });
    fireEvent.change(screen.getByLabelText(/confirm password/i), { target: { value: 'different-pass' } });
    fireEvent.click(screen.getByRole('button', { name: /create account/i }));
    expect(await screen.findByText('Password confirmation does not match.')).toBeInTheDocument();
    expect(registerMock).not.toHaveBeenCalled();
  });

  it('successful register calls register once and closes through auth context', async () => {
    mode = 'create-account';
    registerMock.mockResolvedValueOnce(undefined);
    render(<AuthDialog />);
    fireEvent.change(screen.getByLabelText(/display name/i), { target: { value: 'New User' } });
    fireEvent.change(screen.getByLabelText(/username/i), { target: { value: 'new-user' } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: 'private-pass' } });
    fireEvent.change(screen.getByLabelText(/confirm password/i), { target: { value: 'private-pass' } });
    fireEvent.click(screen.getByRole('button', { name: /create account/i }));
    await waitFor(() => expect(registerMock).toHaveBeenCalledTimes(1));
    expect(registerMock).toHaveBeenCalledWith({
      username: 'new-user',
      display_name: 'New User',
      role: 'Manufacturing Engineer',
      password: 'private-pass',
    });
    expect(window.localStorage.getItem('password')).toBeNull();
  });

  it('duplicate username displays safely', async () => {
    mode = 'create-account';
    registerMock.mockRejectedValueOnce(new Error('That username is already in use.'));
    render(<AuthDialog />);
    fireEvent.change(screen.getByLabelText(/display name/i), { target: { value: 'New User' } });
    fireEvent.change(screen.getByLabelText(/username/i), { target: { value: 'new-user' } });
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: 'private-pass' } });
    fireEvent.change(screen.getByLabelText(/confirm password/i), { target: { value: 'private-pass' } });
    fireEvent.click(screen.getByRole('button', { name: /create account/i }));
    expect(await screen.findByText('That username is already in use.')).toBeInTheDocument();
  });
});
