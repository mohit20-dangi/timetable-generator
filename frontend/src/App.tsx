import { Routes, Route } from 'react-router-dom';
import { SetupWizard } from './pages/SetupWizard';
import { TimetableViewer } from './pages/TimetableViewer';
import { TimetableRuns } from './pages/TimetableRuns';
import { VersionHistory } from './pages/VersionHistory';
import { MyTimetable } from './pages/MyTimetable';
import { Login } from './pages/Login';
import { Layout } from './components/Layout';
import { ProtectedRoute } from './components/ProtectedRoute';
import { AuthProvider } from './context/AuthContext';

function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<Login />} />

        <Route
          path="/"
          element={
            <ProtectedRoute>
              <Layout />
            </ProtectedRoute>
          }
        >
          <Route
            index
            element={
              <ProtectedRoute allowedRoles={['ADMIN']}>
                <SetupWizard />
              </ProtectedRoute>
            }
          />
          <Route
            path="runs"
            element={
              <ProtectedRoute allowedRoles={['ADMIN']}>
                <TimetableRuns />
              </ProtectedRoute>
            }
          />
          <Route
            path="runs/:runId"
            element={
              <ProtectedRoute allowedRoles={['ADMIN']}>
                <TimetableViewer />
              </ProtectedRoute>
            }
          />
          <Route
            path="runs/:runId/versions"
            element={
              <ProtectedRoute allowedRoles={['ADMIN']}>
                <VersionHistory />
              </ProtectedRoute>
            }
          />
          <Route
            path="my-timetable"
            element={
              <ProtectedRoute allowedRoles={['FACULTY', 'STUDENT']}>
                <MyTimetable />
              </ProtectedRoute>
            }
          />
        </Route>
      </Routes>
    </AuthProvider>
  );
}

export default App;
