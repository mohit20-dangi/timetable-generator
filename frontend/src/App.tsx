import { Routes, Route } from 'react-router-dom';
import { SetupWizard } from './pages/SetupWizard';
import { TimetableViewer } from './pages/TimetableViewer';
import { TimetableRuns } from './pages/TimetableRuns';
import { Login } from './pages/Login';
import { Register } from './pages/Register';
import { PublicTimetable } from './pages/PublicTimetable';
import { Layout } from './components/Layout';
import { ProtectedRoute } from './components/ProtectedRoute';
import { AuthProvider } from './context/AuthContext';

function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/public" element={<PublicTimetable />} />

        <Route element={<ProtectedRoute />}>
          <Route path="/" element={<Layout />}>
            <Route index element={<SetupWizard />} />
            <Route path="runs" element={<TimetableRuns />} />
            <Route path="runs/:runId" element={<TimetableViewer />} />
          </Route>
        </Route>
      </Routes>
    </AuthProvider>
  );
}

export default App;
