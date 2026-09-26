import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, RotateCcw, ChevronLeft } from 'lucide-react';
import { adminDataApi } from '../api/client';

const scopes = [
  { value: 'sections', label: 'Sections and lab batches' },
  { value: 'years', label: 'Academic years and sections' },
  { value: 'subjects', label: 'Subjects and subject mappings' },
  { value: 'teachers', label: 'Teachers and teacher mappings' },
  { value: 'rooms', label: 'Rooms' },
  { value: 'constraints', label: 'Constraints, time slots, and bell schedule' },
  { value: 'timetables', label: 'Timetable history' },
  { value: 'all', label: 'Everything except login accounts' },
];

const CONFIRM_PHRASE = 'delete';

/** Its own page, reached deliberately - not sitting at the top of every
 * setup step - and it shows exactly what's kept as well as what's deleted
 * before anything happens (Phase 3.8 / Phase 0.1's preview endpoint). */
export function DangerZonePage() {
  const [scope, setScope] = useState('sections');
  const [preview, setPreview] = useState<{ deletes: Record<string, number>; keeps: Record<string, number> } | null>(null);
  const [confirmText, setConfirmText] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    setPreview(null);
    setConfirmText('');
    setError('');
    adminDataApi.previewReset(scope).then((res) => setPreview(res.data)).catch(() => setError('Could not load a preview for this scope.'));
  }, [scope]);

  const totalDeletes = preview ? Object.values(preview.deletes).reduce((a, b) => a + b, 0) : 0;

  const reset = async () => {
    if (confirmText.trim().toLowerCase() !== CONFIRM_PHRASE) return;
    setBusy(true);
    setMessage('');
    setError('');
    try {
      await adminDataApi.reset(scope);
      setMessage('Reset completed. Setup lists will refresh the next time you open them.');
      setConfirmText('');
      adminDataApi.previewReset(scope).then((res) => setPreview(res.data)).catch(() => {});
    } catch {
      setError('Reset failed. Check that the backend is running and try again.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-2xl">
      <Link to="/settings" className="mb-4 inline-flex items-center gap-1 text-sm text-gray-600 hover:text-gray-900">
        <ChevronLeft size={16} /> Back to Settings
      </Link>

      <div className="rounded-lg border border-amber-200 bg-amber-50 p-5">
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 text-amber-600 shrink-0" size={22} />
          <div>
            <h1 className="text-xl font-semibold text-amber-900">Danger zone</h1>
            <p className="mt-1 text-sm text-amber-800">
              Permanently deletes setup data. Use this only to remove old or incorrect data. Login accounts are
              always preserved, and generated timetable history is only touched when you choose the "Timetable
              history" scope.
            </p>
          </div>
        </div>

        <div className="mt-5">
          <label className="block text-sm font-medium text-amber-900 mb-1">What to reset</label>
          <select value={scope} onChange={(e) => setScope(e.target.value)} className="w-full rounded-lg border border-amber-300 bg-white px-3 py-2 text-sm">
            {scopes.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
        </div>

        {preview && (
          <div className="mt-4 rounded-lg border border-amber-200 bg-white p-4 text-sm">
            <p className="font-medium text-gray-900 mb-2">This will delete:</p>
            {totalDeletes === 0 ? (
              <p className="text-gray-500">Nothing - there's no data in this scope yet.</p>
            ) : (
              <ul className="list-disc pl-5 text-gray-700 space-y-0.5">
                {Object.entries(preview.deletes).filter(([, count]) => count > 0).map(([label, count]) => (
                  <li key={label}>{count} {label.replace(/_/g, ' ')}</li>
                ))}
              </ul>
            )}
            {Object.keys(preview.keeps).length > 0 && (
              <>
                <p className="font-medium text-gray-900 mt-3 mb-1">This will keep:</p>
                <ul className="list-disc pl-5 text-gray-700 space-y-0.5">
                  {Object.entries(preview.keeps).map(([label, count]) => (
                    <li key={label}>{count} {label.replace(/_/g, ' ')}</li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}

        {totalDeletes > 0 && (
          <div className="mt-4">
            <label className="block text-sm font-medium text-amber-900 mb-1">
              Type "{CONFIRM_PHRASE}" to confirm
            </label>
            <input
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              placeholder={CONFIRM_PHRASE}
              className="w-full rounded-lg border border-amber-300 px-3 py-2 text-sm"
            />
          </div>
        )}

        <button
          type="button"
          onClick={reset}
          disabled={busy || totalDeletes === 0 || confirmText.trim().toLowerCase() !== CONFIRM_PHRASE}
          className="mt-4 inline-flex items-center justify-center gap-2 rounded-lg bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <RotateCcw size={16} /> {busy ? 'Resetting...' : 'Reset selected data'}
        </button>

        {message && <p className="mt-3 text-sm text-amber-900">{message}</p>}
        {error && <p className="mt-3 text-sm text-red-700">{error}</p>}
      </div>
    </div>
  );
}
