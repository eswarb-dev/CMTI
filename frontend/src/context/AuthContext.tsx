/* oxlint-disable react/only-export-components, react/set-state-in-effect */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import apiClient, { ApiError } from '../services/apiClient';
import type { AuthUser, RegisterRequest } from '../types/contracts';

export const AUTH_TOKEN_KEY = 'manufacturaiq.auth.token.v1';
export type AuthDialogMode = 'sign-in' | 'create-account';

interface AuthContextType {
  user: AuthUser | null;
  accessToken: string | null;
  authenticated: boolean;
  loading: boolean;
  authState: 'loading' | 'guest' | 'authenticated';
  authDialogMode: AuthDialogMode | null;
  login: (username: string, password: string) => Promise<void>;
  register: (payload: RegisterRequest) => Promise<void>;
  logout: () => void;
  restoreSession: () => Promise<void>;
  openAuthDialog: (mode: AuthDialogMode) => void;
  closeAuthDialog: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [authDialogMode, setAuthDialogMode] = useState<AuthDialogMode | null>(null);

  const restoreSession = useCallback(async () => {
    setLoading(true);
    const token = readToken();
    if (!token) {
      setUser(null);
      setAccessToken(null);
      setLoading(false);
      return;
    }
    try {
      const currentUser = await apiClient.getCurrentUser(token);
      setUser(currentUser);
      setAccessToken(token);
    } catch {
      removeToken();
      setUser(null);
      setAccessToken(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void restoreSession();
  }, [restoreSession]);

  const login = useCallback(async (username: string, password: string) => {
    const response = await apiClient.login(username, password);
    saveToken(response.access_token);
    setAccessToken(response.access_token);
    setUser(response.user);
    setAuthDialogMode(null);
  }, []);

  const register = useCallback(async (payload: RegisterRequest) => {
    const response = await apiClient.register(payload);
    saveToken(response.access_token);
    setAccessToken(response.access_token);
    setUser(response.user);
    setAuthDialogMode(null);
  }, []);

  const logout = useCallback(() => {
    removeToken();
    setAccessToken(null);
    setUser(null);
  }, []);

  const openAuthDialog = useCallback((mode: AuthDialogMode) => {
    setAuthDialogMode(mode);
  }, []);

  const closeAuthDialog = useCallback(() => {
    setAuthDialogMode(null);
  }, []);

  const authenticated = Boolean(user && accessToken);
  const authState = loading ? 'loading' : authenticated ? 'authenticated' : 'guest';

  const value = useMemo<AuthContextType>(() => ({
    user,
    accessToken,
    authenticated,
    loading,
    authState,
    authDialogMode,
    login,
    register,
    logout,
    restoreSession,
    openAuthDialog,
    closeAuthDialog,
  }), [
    accessToken,
    authenticated,
    authDialogMode,
    authState,
    closeAuthDialog,
    loading,
    login,
    logout,
    openAuthDialog,
    register,
    restoreSession,
    user,
  ]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
}

export function useOptionalAuth(): AuthContextType | null {
  return useContext(AuthContext);
}

export function isBackendUnreachable(error: unknown): boolean {
  return error instanceof ApiError && error.status === undefined;
}

function readToken(): string | null {
  try {
    return window.localStorage.getItem(AUTH_TOKEN_KEY);
  } catch {
    return null;
  }
}

function saveToken(token: string): void {
  window.localStorage.setItem(AUTH_TOKEN_KEY, token);
}

function removeToken(): void {
  try {
    window.localStorage.removeItem(AUTH_TOKEN_KEY);
  } catch {
    // In-memory auth state is still cleared by logout.
  }
}
