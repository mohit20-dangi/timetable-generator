import { Routes, Route, Navigate } from 'react-router-dom';
import { useAuth } from './context/AuthContext';
import { Dashboard } from './pages/Dashboard';
import { YearsSectionsPage } from './pages/YearsSectionsPage';
import { SubjectsPage } from './pages/SubjectsPage';
import { CurriculumPage } from './pages/CurriculumPage';
import { ElectivesPage } from './pages/ElectivesPage';
import { LabBatchesPage } from './pages/LabBatchesPage';
import { LabRotationsPage } from './pages/LabRotationsPage';
import { TeachersPage } from './pages/TeachersPage';
import { RoomsPage } from './pages/RoomsPage';
import { ImportPage } from './pages/ImportPage';
import { FirstYearImportPage } from './pages/FirstYearImportPage';
import { AISetupPage } from './pages/AISetupPage';
import { SchedulingRulesPage } from './pages/SchedulingRulesPage';
import { SettingsPage } from './pages/SettingsPage';
import { DangerZonePage } from './pages/DangerZonePage';
import { TimetableViewer } from './pages/TimetableViewer';
import { TimetableRuns } from './pages/TimetableRuns';
import { RemedialPlanner } from './pages/RemedialPlanner';
import { VersionHistory } from './pages/VersionHistory';
import { MyTimetable } from './pages/MyTimetable';
import { Login } from './pages/Login';
import { PublicTimetable } from './pages/PublicTimetable';
import { Layout } from './components/Layout';
import { SetupLayout } from './components/SetupLayout';
import { ProtectedRoute } from './components/ProtectedRoute';
import { ADMIN_ROLES, TIMETABLE_ROLES } from './auth/roles';
import { DepartmentsPage } from './pages/DepartmentsPage';
import { AuthProvider } from './context/AuthContext';
import { DepartmentProvider } from './context/DepartmentContext';

function HomeRedirect() {
  const { user } = useAuth();
  if (user?.role === 'HOD') return <Navigate to="/runs" replace />;
  if (user?.role === 'TEACHER') return <Navigate to="/my-timetable" replace />;
  return <Dashboard />;
}

// The root path is the public class-timetable view for anyone not signed
// in - no login wall on the way in. A signed-in account still lands on its
// usual dashboard/runs/my-timetable home via HomeRedirect below.
function RootRoute() {
  const { user, loading } = useAuth();
  if (loading) return <div className="p-8 text-sm text-gray-500">Loading...</div>;
  if (!user) return <PublicTimetable />;
  return <Layout />;
}

function App() {
  return (
    <AuthProvider>
      <DepartmentProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/timetables" element={<PublicTimetable />} />

        <Route path="/" element={<RootRoute />}>
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
              <ProtectedRoute allowedRoles={ADMIN_ROLES}>
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
            <Route path="lab-rotations" element={<LabRotationsPage />} />
            <Route path="teachers" element={<TeachersPage />} />
            <Route path="rooms" element={<RoomsPage />} />
            <Route path="first-year" element={<FirstYearImportPage />} />
            <Route path="ai-assistant" element={<AISetupPage />} />
            <Route path="import" element={<ImportPage />} />
          </Route>
          <Route
            path="scheduling-rules"
            element={
              <ProtectedRoute allowedRoles={ADMIN_ROLES}>
                <SchedulingRulesPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="departments"
            element={
              <ProtectedRoute allowedRoles={ADMIN_ROLES}>
                <DepartmentsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="settings"
            element={
              <ProtectedRoute allowedRoles={ADMIN_ROLES}>
                <SettingsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="settings/danger-zone"
            element={
              <ProtectedRoute allowedRoles={ADMIN_ROLES}>
                <DangerZonePage />
              </ProtectedRoute>
            }
          />
          <Route
            path="runs"
            element={
              <ProtectedRoute allowedRoles={TIMETABLE_ROLES}>
                <TimetableRuns />
              </ProtectedRoute>
            }
          />
          <Route
            path="remedial"
            element={
              <ProtectedRoute allowedRoles={TIMETABLE_ROLES}>
                <RemedialPlanner />
              </ProtectedRoute>
            }
          />
          <Route
            path="runs/:runId"
            element={
              <ProtectedRoute allowedRoles={TIMETABLE_ROLES}>
                <TimetableViewer />
              </ProtectedRoute>
            }
          />
          <Route
            path="runs/:runId/versions"
            element={
              <ProtectedRoute allowedRoles={TIMETABLE_ROLES}>
                <VersionHistory />
              </ProtectedRoute>
            }
          />
          <Route
            path="my-timetable"
            element={
              <ProtectedRoute allowedRoles={['TEACHER']}>
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
