import { useState } from 'react';
import { AlertTriangle, RotateCcw } from 'lucide-react';
import { adminDataApi } from '../api/client';

const scopes = [
  { value: 'sections', label: 'Sections and lab batches' },
  { value: 'years', label: 'Academic years and sections' },
  { value: 'subjects', label: 'Subjects and subject mappings' },
  { value: 'teachers', label: 'Teachers and teacher mappings' },
  { value: 'rooms', label: 'Rooms' },
  { value: 'constraints', label: 'Constraints, time slots, and timetable history' },
  { value: 'all', label: 'Everything except login accounts' },
];

export function DataResetPanel() {
  const [scope, setScope] = useState('sections');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  const reset = async () => {
    const label = scopes.find((item) => item.value === scope)?.label;
    if (!window.confirm(`This will permanently delete ${label?.toLowerCase()}. Continue?`)) return;
    setBusy(true);
    setMessage('');
    try {
      await adminDataApi.reset(scope);
      setMessage('Reset completed. Refresh the setup lists before adding new data.');
    } catch (error) {
      console.error('Reset failed:', error);
      setMessage('Reset failed. Check that the backend is running and try again.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="mb-6 rounded-lg border border-amber-200 bg-amber-50 p-4">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 text-amber-600" size={20} />
        <div className="flex-1">
          <h2 className="font-semibold text-amber-900">Reset setup data</h2>
          <p className="mt-1 text-sm text-amber-800">Use this only when you want to remove old or incorrect data. Login accounts are preserved.</p>
          <div className="mt-3 flex flex-col gap-2 sm:flex-row">
            <select value={scope} onChange={(event) => setScope(event.target.value)} className="rounded-lg border border-amber-300 bg-white px-3 py-2 text-sm">
              {scopes.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
            <button type="button" onClick={reset} disabled={busy} className="inline-flex items-center justify-center gap-2 rounded-lg bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50">
              <RotateCcw size={16} /> {busy ? 'Resetting...' : 'Reset selected data'}
            </button>
          </div>
          {message && <p className="mt-2 text-sm text-amber-900">{message}</p>}
        </div>
      </div>
    </section>
  );
}
