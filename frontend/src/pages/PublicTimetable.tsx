import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { publicTimetableApi } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { Download, LogIn } from 'lucide-react';

interface PublicSection {
  id: string;
  name: string;
  year_id: string;
  year_name: string | null;
  department_id: string | null;
  department_name: string | null;
}

interface ViewCell {
  day: string;
  period: number;
  is_lunch: boolean;
  covered: boolean;
  span: number;
  color: string | null;
  blocks: string[][];
}

interface SectionView {
  published: boolean;
  section_label?: string;
  department_name?: string;
  days?: string[];
  periods?: number[];
  period_times?: Record<string, string>;
  cells?: ViewCell[];
  legend?: { subjects: [string, string][]; teachers: [string, string][] };
}

const DAY_LABELS: Record<string, string> = {
  Mon: 'Monday', Tue: 'Tuesday', Wed: 'Wednesday', Thu: 'Thursday', Fri: 'Friday', Sat: 'Saturday', Sun: 'Sunday',
};

// No login required: anyone can look up a CSE class's published timetable
// by year -> section (CSE is the only department this view offers),
// rendered in the same merged-cell/coloured layout as the PDF and Excel
// exports (backend: exporters.build_section_view), with the same
// PDF/Excel/calendar downloads. Deliberately no lookup by room or teacher -
// those views stay behind a login.
export function PublicTimetable() {
  const { user } = useAuth();
  const [sections, setSections] = useState<PublicSection[] | null>(null);
  const [sectionsError, setSectionsError] = useState<string | null>(null);
  const [departmentId, setDepartmentId] = useState('');
  const [yearId, setYearId] = useState('');
  const [sectionId, setSectionId] = useState('');

  const [view, setView] = useState<SectionView | null>(null);
  const [viewError, setViewError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);

  useEffect(() => {
    publicTimetableApi
      .listSections()
      .then((res) => {
        setSections(res.data);
        // CSE is the only department this view offers - no picker needed.
        const cse = (res.data as PublicSection[]).find(
          (s) => (s.department_id || '').toLowerCase() === 'cse' || (s.department_name || '').toLowerCase().includes('computer'),
        );
        setDepartmentId(cse?.department_id || res.data[0]?.department_id || '');
      })
      .catch((err) => setSectionsError(err?.response?.data?.detail || 'Could not load the list of classes.'));
  }, []);

  useEffect(() => {
    if (!sectionId) {
      setView(null);
      return;
    }
    setView(null);
    setViewError(null);
    publicTimetableApi
      .getSectionView(sectionId)
      .then((res) => setView(res.data))
      .catch((err) => setViewError(err?.response?.data?.detail || 'Could not load this class timetable.'));
  }, [sectionId]);

  const years = useMemo(() => {
    const seen = new Map<string, string>();
    for (const s of sections || []) {
      if (s.department_id === departmentId && s.year_id) seen.set(s.year_id, s.year_name || s.year_id);
    }
    return [...seen.entries()];
  }, [sections, departmentId]);

  const sectionsForYear = (sections || []).filter((s) => s.year_id === yearId);

  const cellMap = useMemo(() => {
    const map: Record<number, Record<string, ViewCell>> = {};
    for (const cell of view?.cells || []) {
      map[cell.period] = map[cell.period] || {};
      map[cell.period][cell.day] = cell;
    }
    return map;
  }, [view]);

  const handleDownload = async (format: 'pdf' | 'xlsx' | 'ics') => {
    if (!sectionId) return;
    setDownloading(format);
    try {
      const res = await publicTimetableApi.download(sectionId, format);
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const link = document.createElement('a');
      link.href = url;
      link.download = `timetable_${sectionId}.${format}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch {
      setViewError('Could not download the timetable. Try again.');
    } finally {
      setDownloading(null);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-6xl mx-auto px-4 py-8">
        <div className="flex items-start justify-between mb-6">
          <div>
            <h1 className="text-xl font-bold text-gray-900 mb-1">Class Timetables</h1>
            <p className="text-sm text-gray-500">Look up any class's published timetable - no login needed.</p>
          </div>
          <Link
            to={user ? '/' : '/login'}
            className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 hover:shadow transition-colors"
          >
            <LogIn size={16} /> {user ? 'Go to dashboard' : 'Sign in'}
          </Link>
        </div>

        {sectionsError && <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700 mb-4">{sectionsError}</div>}

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 mb-6">
          <select
            value={yearId}
            onChange={(e) => { setYearId(e.target.value); setSectionId(''); }}
            disabled={!departmentId}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white disabled:bg-gray-100"
          >
            <option value="">Select year</option>
            {years.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select>
          <select
            value={sectionId}
            onChange={(e) => setSectionId(e.target.value)}
            disabled={!yearId}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white disabled:bg-gray-100"
          >
            <option value="">Select section</option>
            {sectionsForYear.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </div>

        {!sectionId && <div className="text-sm text-gray-500">Pick a year and section to view its timetable.</div>}
        {sectionId && viewError && <div className="text-sm text-red-600">{viewError}</div>}
        {sectionId && !viewError && view === null && <div className="text-sm text-gray-500">Loading...</div>}
        {sectionId && !viewError && view && !view.published && (
          <div className="text-sm text-gray-500">No published timetable yet for this class.</div>
        )}

        {sectionId && view && view.published && view.days && view.periods && (
          <div>
            <div className="flex items-center justify-between mb-3">
              <div>
                <div className="text-xs uppercase tracking-wide text-gray-400">{view.department_name}</div>
                <h2 className="text-lg font-semibold text-gray-900">{view.section_label}</h2>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => handleDownload('pdf')}
                  disabled={downloading !== null}
                  className="flex items-center gap-1.5 rounded-lg bg-red-600 px-3 py-2 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
                >
                  <Download size={14} /> {downloading === 'pdf' ? 'Preparing...' : 'PDF'}
                </button>
                <button
                  onClick={() => handleDownload('xlsx')}
                  disabled={downloading !== null}
                  className="flex items-center gap-1.5 rounded-lg bg-green-600 px-3 py-2 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50"
                >
                  <Download size={14} /> {downloading === 'xlsx' ? 'Preparing...' : 'Excel'}
                </button>
                <button
                  onClick={() => handleDownload('ics')}
                  disabled={downloading !== null}
                  className="flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                >
                  <Download size={14} /> {downloading === 'ics' ? 'Preparing...' : 'Calendar (.ics)'}
                </button>
              </div>
            </div>

            <div className="overflow-x-auto bg-white rounded-xl border border-gray-200">
              <table className="min-w-full text-xs border-collapse">
                <thead>
                  <tr>
                    <th className="border border-gray-200 bg-[#1E3A5F] text-white px-3 py-2 text-left">Period / Time</th>
                    {view.days.map((day) => (
                      <th key={day} className="border border-gray-200 bg-[#1E3A5F] text-white px-3 py-2 text-center">
                        {DAY_LABELS[day] || day}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {view.periods.map((period) => (
                    <tr key={period}>
                      <td className="border border-gray-200 px-3 py-2 font-medium bg-gray-50 whitespace-nowrap">
                        <div>Period {period}</div>
                        <div className="text-[11px] font-normal text-gray-400">{view.period_times?.[String(period)]}</div>
                      </td>
                      {view.days!.map((day) => {
                        const cell = cellMap[period]?.[day];
                        if (!cell || cell.covered) return null;
                        if (cell.is_lunch) {
                          return (
                            <td key={day} className="border border-gray-200 px-3 py-2 text-center italic text-gray-400 bg-gray-50">
                              Lunch
                            </td>
                          );
                        }
                        return (
                          <td
                            key={day}
                            rowSpan={cell.span}
                            className="border border-gray-200 px-3 py-2 align-middle text-center"
                            style={cell.color ? { backgroundColor: `#${cell.color}` } : undefined}
                          >
                            {cell.blocks.length ? (
                              <div className="space-y-2">
                                {cell.blocks.map((lines, i) => (
                                  <div key={i}>
                                    {lines.map((line, j) => (
                                      <div key={j} className={j === 0 ? 'font-semibold text-gray-900' : 'text-gray-600'}>
                                        {line}
                                      </div>
                                    ))}
                                  </div>
                                ))}
                              </div>
                            ) : (
                              <span className="text-gray-300">—</span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {view.legend && (view.legend.subjects.length > 0 || view.legend.teachers.length > 0) && (
              <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2 text-xs text-gray-600">
                {view.legend.subjects.length > 0 && (
                  <div>
                    <div className="font-semibold text-gray-800 mb-1">Subjects</div>
                    {view.legend.subjects.map(([code, name]) => (
                      <div key={code}>{code} — {name}</div>
                    ))}
                  </div>
                )}
                {view.legend.teachers.length > 0 && (
                  <div>
                    <div className="font-semibold text-gray-800 mb-1">Faculty</div>
                    {view.legend.teachers.map(([initials, name]) => (
                      <div key={initials}>{initials} — {name}</div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
