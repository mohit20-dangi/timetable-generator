import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { authApi } from '../api/client';

export interface CurrentUser {
  id: number;
  email: string;
  full_name: string;
  role: 'ADMIN' | 'FACULTY' | 'STUDENT';
  teacher_id: string | null;
  section_id: string | null;
}

interface AuthContextValue {
  user: CurrentUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('access_token');
    if (!token) {
      setLoading(false);
      return;
    }

    let cancelled = false;
    authApi
      .me()
      .then((res) => {
        // Do not let an older session check overwrite a newer login.
        if (!cancelled && localStorage.getItem('access_token') === token) {
          setUser(res.data);
        }
      })
      .catch(() => {
        // A stale in-flight request must not clear a token created by login.
        if (!cancelled && localStorage.getItem('access_token') === token) {
          localStorage.removeItem('access_token');
          localStorage.removeItem('user');
          setUser(null);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const login = async (email: string, password: string) => {
    const res = await authApi.login(email, password);
    localStorage.setItem('access_token', res.data.access_token);
    localStorage.setItem('user', JSON.stringify(res.data.user));
    setUser(res.data.user);
  };

  const logout = () => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('user');
    setUser(null);
    window.location.href = '/login';
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
