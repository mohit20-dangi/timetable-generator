import { Routes, Route, Navigate } from 'react-router-dom';
import { useAuth } from './context/AuthContext';
import { Dashboard } from './pages/Dashboard';
import { YearsSectionsPage } from './pages/YearsSectionsPage';
import { SubjectsPage } from './pages/SubjectsPage';
import { CurriculumPage } from './pages/CurriculumPage';
import { ElectivesPage } from './pages/ElectivesPage';
import { LabBatchesPage } from './pages/LabBatchesPage';
import { TeachersPage } from './pages/TeachersPage';
import { RoomsPage } from './pages/RoomsPage';
import { ImportPage } from './pages/ImportPage';
import { SchedulingRulesPage } from './pages/SchedulingRulesPage';
import { SettingsPage } from './pages/SettingsPage';
import { DangerZonePage } from './pages/DangerZonePage';
import { TimetableViewer } from './pages/TimetableViewer';
import { TimetableRuns } from './pages/TimetableRuns';
import { VersionHistory } from './pages/VersionHistory';
import { MyTimetable } from './pages/MyTimetable';
import { Login } from './pages/Login';
import { Layout } from './components/Layout';
import { SetupLayout } from './components/SetupLayout';
import { ProtectedRoute } from './components/ProtectedRoute';
import { AuthProvider } from './context/AuthContext';
import { DepartmentProvider } from './context/DepartmentContext';

function HomeRedirect() {
  const { user } = useAuth();
  if (user?.role === 'HOD') return <Navigate to="/runs" replace />;
  if (user?.role === 'FACULTY' || user?.role === 'STUDENT') return <Navigate to="/my-timetable" replace />;
  return <Dashboard />;
}

function App() {
  return (
    <AuthProvider>
      <DepartmentProvider>
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
              <ProtectedRoute>
                <HomeRedirect />
              </ProtectedRoute>
            }
          />
          <Route
            path="setup"
            element={
              <ProtectedRoute allowedRoles={['ADMIN']}>
                <SetupLayout />
              </ProtectedRoute>
            }
          >
            <Route index element={<Navigate to="years-sections" replace />} />
            <Route path="years-sections" element={<YearsSectionsPage />} />
            <Route path="subjects" element={<SubjectsPage />} />
            <Route path="curriculum" element={<CurriculumPage />} />
            <Route path="electives" element={<ElectivesPage />} />
            <Route path="lab-batches" element={<LabBatchesPage />} />
            <Route path="teachers" element={<TeachersPage />} />
            <Route path="rooms" element={<RoomsPage />} />
            <Route path="import" element={<ImportPage />} />
          </Route>
          <Route
            path="scheduling-rules"
            element={
              <ProtectedRoute allowedRoles={['ADMIN']}>
                <SchedulingRulesPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="settings"
            element={
              <ProtectedRoute allowedRoles={['ADMIN']}>
                <SettingsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="settings/danger-zone"
            element={
              <ProtectedRoute allowedRoles={['ADMIN']}>
                <DangerZonePage />
              </ProtectedRoute>
            }
          />
          <Route
            path="runs"
            element={
              <ProtectedRoute allowedRoles={['ADMIN', 'HOD']}>
                <TimetableRuns />
              </ProtectedRoute>
            }
          />
          <Route
            path="runs/:runId"
            element={
              <ProtectedRoute allowedRoles={['ADMIN', 'HOD']}>
                <TimetableViewer />
              </ProtectedRoute>
            }
          />
          <Route
            path="runs/:runId/versions"
            element={
              <ProtectedRoute allowedRoles={['ADMIN', 'HOD']}>
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
      </DepartmentProvider>
    </AuthProvider>
  );
}

export default App;
