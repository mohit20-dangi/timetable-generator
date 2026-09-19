import { createContext, useContext, useState, useCallback, ReactNode } from 'react';
import { authApi } from '../api/client';

interface AuthContextValue {
  isAuthenticated: boolean;
  username: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('access_token'));
  const [username, setUsername] = useState<string | null>(() => localStorage.getItem('admin_username'));

  const login = useCallback(async (usernameInput: string, password: string) => {
    const response = await authApi.login(usernameInput, password);
    const accessToken = response.data.access_token;
    localStorage.setItem('access_token', accessToken);
    localStorage.setItem('admin_username', usernameInput);
    setToken(accessToken);
    setUsername(usernameInput);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('admin_username');
    setToken(null);
    setUsername(null);
  }, []);

  return (
    <AuthContext.Provider value={{ isAuthenticated: !!token, username, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return ctx;
}
