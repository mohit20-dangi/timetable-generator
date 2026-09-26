import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  yearsApi, sectionsApi, subjectsApi, teachersApi, roomsApi, timetableApi,
} from '../api/client';
import { TimetableRun } from '../types';
import { GenerateButton } from '../components/GenerateButton';
import { CheckCircle2, Circle, Calendar, ArrowRight } from 'lucide-react';

interface ChecklistItem {
  label: string;
  count: number;
  to: string;
}

/** The landing page: what's configured, what's missing, the last
 * timetable, and Generate - replacing the old wizard's step 1 (Phase 3.2/3.9). */
export function Dashboard() {
  const [items, setItems] = useState<ChecklistItem[] | null>(null);
  const [lastRun, setLastRun] = useState<TimetableRun | null>(null);

  useEffect(() => {
    Promise.all([
      yearsApi.list(), sectionsApi.list(), subjectsApi.list(), teachersApi.list(), roomsApi.list(), timetableApi.listRuns(),
    ]).then(([years, sections, subjects, teachers, rooms, runs]) => {
      setItems([
        { label: 'Academic years', count: years.data.length, to: '/setup/years-sections' },
        { label: 'Sections', count: sections.data.length, to: '/setup/years-sections' },
        { label: 'Subjects', count: subjects.data.length, to: '/setup/subjects' },
        { label: 'Teachers', count: teachers.data.length, to: '/setup/teachers' },
        { label: 'Rooms', count: rooms.data.length, to: '/setup/rooms' },
      ]);
      const completedRuns = (runs.data as TimetableRun[])
        .filter((run) => run.status === 'completed')
        .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
      setLastRun(completedRuns[0] || null);
    }).catch(() => setItems([]));
  }, []);

  const missing = (items || []).filter((item) => item.count === 0);

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Dashboard</h1>
        <p className="text-gray-600">What's configured, what's still missing, and your last timetable.</p>
      </div>

      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Setup status</h2>
        {items === null ? (
          <p className="text-sm text-gray-500">Loading...</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {items.map((item) => (
              <Link
                key={item.label} to={item.to}
                className="flex items-center justify-between rounded-lg border border-gray-200 px-4 py-3 hover:bg-gray-50 transition-colors"
              >
                <span className="flex items-center gap-2 text-sm text-gray-800">
                  {item.count > 0 ? <CheckCircle2 size={18} className="text-green-500" /> : <Circle size={18} className="text-gray-300" />}
                  {item.label}
                </span>
                <span className="text-sm text-gray-500">{item.count}</span>
              </Link>
            ))}
          </div>
        )}
        {missing.length > 0 && (
          <p className="mt-4 text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
            Still missing: {missing.map((m) => m.label).join(', ')}.
          </p>
        )}
      </div>

      {lastRun && (
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-3 flex items-center gap-2"><Calendar size={20} /> Last timetable</h2>
          <div className="flex items-center justify-between">
            <div className="text-sm text-gray-600">
              Created {new Date(lastRun.created_at).toLocaleString()}
              {lastRun.is_published && <span className="ml-2 text-green-700 font-medium">Published</span>}
            </div>
            <Link to={`/runs/${lastRun.id}`} className="flex items-center gap-1 text-sm font-medium text-blue-600 hover:text-blue-800">
              View <ArrowRight size={16} />
            </Link>
          </div>
        </div>
      )}

      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <GenerateButton />
      </div>
    </div>
  );
}
