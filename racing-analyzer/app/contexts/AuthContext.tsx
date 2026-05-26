'use client';

import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';
import { useRouter } from 'next/navigation';
import { API_BASE_URL } from '../../utils/config';
import webSocketService from '../services/WebSocketService';

interface User {
  id: number;
  username: string;
  email: string;
  role: string;
}

export type LoginResult =
  | { ok: true; user: User }
  | { ok: false; code: 'email_not_verified'; email: string }
  | { ok: false; code: 'invalid_credentials' | 'rate_limited' | 'captcha_failed' | 'unknown'; message?: string };

interface AuthContextType {
  user: User | null;
  loading: boolean;
  csrfToken: string | null;
  login: (
    username: string,
    password: string,
    turnstileToken: string,
  ) => Promise<LoginResult>;
  logout: () => Promise<void>;
  checkAuth: () => Promise<void>;
  apiFetch: (path: string, init?: RequestInit) => Promise<Response>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [csrfToken, setCsrfToken] = useState<string | null>(null);
  const router = useRouter();

  const fetchCsrf = useCallback(async () => {
    try {
      const resp = await fetch(`${API_BASE_URL}/api/auth/csrf`, {
        credentials: 'include',
      });
      if (!resp.ok) return;
      const data = await resp.json();
      setCsrfToken(data.csrfToken ?? null);
    } catch (err) {
      console.error('CSRF token fetch failed:', err);
    }
  }, []);

  const checkAuth = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/auth/check`, {
        credentials: 'include',
      });
      const data = await response.json();
      if (data.authenticated) {
        setUser(data.user);
        localStorage.setItem('user', JSON.stringify(data.user));
      } else {
        setUser(null);
        localStorage.removeItem('user');
      }
    } catch (error) {
      console.error('Auth check failed:', error);
      setUser(null);
      localStorage.removeItem('user');
    } finally {
      setLoading(false);
    }
  }, []);

  const apiFetch = useCallback(
    async (path: string, init: RequestInit = {}): Promise<Response> => {
      const method = (init.method ?? 'GET').toUpperCase();
      const headers = new Headers(init.headers ?? {});
      if (UNSAFE.has(method) && csrfToken) {
        headers.set('X-CSRF-Token', csrfToken);
      }
      // Force JSON content-type for bodies unless caller overrode it.
      if (init.body && !headers.has('Content-Type')) {
        headers.set('Content-Type', 'application/json');
      }
      return fetch(`${API_BASE_URL}${path}`, {
        credentials: 'include',
        ...init,
        headers,
      });
    },
    [csrfToken],
  );

  const login = useCallback(
    async (username: string, password: string, turnstileToken: string): Promise<LoginResult> => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ username, password, turnstile_token: turnstileToken }),
        });
        const data = await response.json().catch(() => ({}));
        if (response.ok && data.success) {
          setUser(data.user);
          localStorage.setItem('user', JSON.stringify(data.user));
          await fetchCsrf();
          await checkAuth();
          return { ok: true, user: data.user };
        }
        if (response.status === 401 && data.error === 'email_not_verified') {
          return { ok: false, code: 'email_not_verified', email: data.email };
        }
        if (response.status === 429) {
          return { ok: false, code: 'rate_limited', message: data.error };
        }
        if (response.status === 403 && data.error === 'captcha_failed') {
          return { ok: false, code: 'captcha_failed' };
        }
        return { ok: false, code: 'invalid_credentials', message: data.error };
      } catch (error) {
        console.error('Login failed:', error);
        return { ok: false, code: 'unknown' };
      }
    },
    [checkAuth, fetchCsrf],
  );

  const logout = useCallback(async () => {
    try {
      await apiFetch('/api/auth/logout', { method: 'POST' });
    } catch (error) {
      console.error('Logout failed:', error);
    } finally {
      setUser(null);
      localStorage.removeItem('user');
      // Force a new CSRF token for the next anonymous session.
      await fetchCsrf();
      router.push('/login');
    }
  }, [apiFetch, fetchCsrf, router]);

  useEffect(() => {
    // Get a CSRF token first, then check auth.
    (async () => {
      await fetchCsrf();
      await checkAuth();
    })();
  }, [fetchCsrf, checkAuth]);

  // Phase 2.5: subscribe to per-user prefs Socket.IO room so other tabs/devices
  // can push us "go re-fetch" pings when prefs change elsewhere.
  useEffect(() => {
    if (user?.id) {
      webSocketService.subscribeToUserPrefs(user.id);
      return () => {
        webSocketService.unsubscribeFromUserPrefs();
      };
    }
  }, [user?.id]);

  return (
    <AuthContext.Provider
      value={{ user, loading, csrfToken, login, logout, checkAuth, apiFetch }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
