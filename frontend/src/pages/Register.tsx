import { useState, FormEvent } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { authApi } from '../api/client';

export function Register() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [inviteToken, setInviteToken] = useState(searchParams.get('token') || '');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await authApi.register({ invite_token: inviteToken, username, password });
      setSuccess(true);
      setTimeout(() => navigate('/login'), 1500);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Registration failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <form onSubmit={handleSubmit} className="w-full max-w-sm bg-white p-8 rounded-lg border border-gray-200 space-y-4">
        <h1 className="text-xl font-bold text-blue-600">Admin Registration</h1>
        <p className="text-xs text-gray-500">Admin accounts are invite-only. You need a token from an existing admin.</p>
        {error && <p className="text-sm text-red-600">{error}</p>}
        {success && <p className="text-sm text-green-600">Account created! Redirecting to login...</p>}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Invite Token</label>
          <input
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            value={inviteToken}
            onChange={(e) => setInviteToken(e.target.value)}
            required
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
          <input
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
          <input
            type="password"
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={8}
            required
          />
        </div>
        <button
          type="submit"
          disabled={loading}
          className="w-full bg-blue-600 text-white rounded-md py-2 text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? 'Creating account...' : 'Register'}
        </button>
        <p className="text-xs text-gray-500 text-center">
          Already have an account? <Link to="/login" className="text-blue-600">Sign in</Link>
        </p>
      </form>
    </div>
  );
}
