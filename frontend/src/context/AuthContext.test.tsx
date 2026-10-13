import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { AuthProvider, AUTH_TOKEN_KEY, useAuth } from './AuthContext';
import apiClient from '../services/apiClient';

vi.mock('../services/apiClient', () => ({
  default: {
    login: vi.fn(),
    register: vi.fn(),
    getCurrentUser: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status?: number;
    constructor(message: string, status?: number) {
      super(message);
      this.status = status;
    }
  },
}));

function Probe() {
  const auth = useAuth();
  return (
    <div>
      <span data-testid="auth-state">{auth.loading ? 'loading' : auth.authenticated ? auth.user?.display_name : 'login'}</span>
      <button onClick={() => void auth.login('eswar', 'private-pass')}>login</button>
      <button onClick={() => void auth.register({
        username: 'new-user',
        display_name: 'New User',
        role: 'Engineer',
        password: 'private-pass',
      })}>register</button>
      <button onClick={auth.logout}>logout</button>
    </div>
  );
}

describe('AuthContext', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.mocked(apiClient.login).mockReset();
    vi.mocked(apiClient.register).mockReset();
    vi.mocked(apiClient.getCurrentUser).mockReset();
  });

  it('register stores token and authenticates without clearing other local storage', async () => {
    window.localStorage.setItem('manufacturaiq.conversations.v1', '[{"id":"conv"}]');
    vi.mocked(apiClient.register).mockResolvedValueOnce({
      access_token: 'registered-token',
      token_type: 'bearer',
      user: { id: 'u2', username: 'new-user', display_name: 'New User', role: 'Engineer' },
    });
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId('auth-state')).toHaveTextContent('login'));
    fireEvent.click(screen.getByRole('button', { name: 'register' }));
    expect(await screen.findByText('New User')).toBeInTheDocument();
    expect(window.localStorage.getItem(AUTH_TOKEN_KEY)).toBe('registered-token');
    expect(window.localStorage.getItem('manufacturaiq.conversations.v1')).toBe('[{"id":"conv"}]');
  });

  afterEach(() => {
    window.localStorage.clear();
  });

  it('valid login stores token and displays authenticated app state', async () => {
    vi.mocked(apiClient.login).mockResolvedValueOnce({
      access_token: 'token',
      token_type: 'bearer',
      user: { id: 'u1', username: 'eswar', display_name: 'Eswar Balu', role: 'Manufacturing Engineer' },
    });
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId('auth-state')).toHaveTextContent('login'));
    fireEvent.click(screen.getByRole('button', { name: 'login' }));
    expect(await screen.findByText('Eswar Balu')).toBeInTheDocument();
    expect(window.localStorage.getItem(AUTH_TOKEN_KEY)).toBe('token');
  });

  it('restores valid token after reload', async () => {
    window.localStorage.setItem(AUTH_TOKEN_KEY, 'token');
    vi.mocked(apiClient.getCurrentUser).mockResolvedValueOnce({
      id: 'u1',
      username: 'eswar',
      display_name: 'Eswar Balu',
      role: 'Manufacturing Engineer',
    });
    render(<AuthProvider><Probe /></AuthProvider>);
    expect(await screen.findByText('Eswar Balu')).toBeInTheDocument();
  });

  it('removes invalid or expired token on restore', async () => {
    window.localStorage.setItem(AUTH_TOKEN_KEY, 'expired');
    vi.mocked(apiClient.getCurrentUser).mockRejectedValueOnce(new Error('Invalid or expired token.'));
    render(<AuthProvider><Probe /></AuthProvider>);
    await waitFor(() => expect(window.localStorage.getItem(AUTH_TOKEN_KEY)).toBeNull());
    expect(screen.getByTestId('auth-state')).toHaveTextContent('login');
  });

  it('logout clears token but leaves other local storage intact', async () => {
    window.localStorage.setItem(AUTH_TOKEN_KEY, 'token');
    window.localStorage.setItem('manufacturaiq.conversations.v1', '[]');
    vi.mocked(apiClient.getCurrentUser).mockResolvedValueOnce({
      id: 'u1',
      username: 'eswar',
      display_name: 'Eswar Balu',
      role: 'Manufacturing Engineer',
    });
    render(<AuthProvider><Probe /></AuthProvider>);
    await screen.findByText('Eswar Balu');
    fireEvent.click(screen.getByRole('button', { name: 'logout' }));
    expect(window.localStorage.getItem(AUTH_TOKEN_KEY)).toBeNull();
    expect(window.localStorage.getItem('manufacturaiq.conversations.v1')).toBe('[]');
  });
});
