import { Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export function ProtectedRoute({
  children,
  allowedRoles,
}: {
  children: JSX.Element;
  allowedRoles?: Array<'ADMIN' | 'FACULTY' | 'STUDENT'>;
}) {
  const { user, loading } = useAuth();

  if (loading) {
    return <div className="p-8 text-sm text-gray-500">Loading...</div>;
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  if (allowedRoles && !allowedRoles.includes(user.role)) {
    return (
      <div className="p-8 text-sm text-red-600">
        You don't have permission to view this page.
      </div>
    );
  }
  return children;
}
