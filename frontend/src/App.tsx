import { Routes, Route } from 'react-router-dom';
import { SetupWizard } from './pages/SetupWizard';
import { TimetableViewer } from './pages/TimetableViewer';
import { TimetableRuns } from './pages/TimetableRuns';
import { Layout } from './components/Layout';

function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<SetupWizard />} />
        <Route path="runs" element={<TimetableRuns />} />
        <Route path="runs/:runId" element={<TimetableViewer />} />
      </Route>
    </Routes>
  );
}

export default App;