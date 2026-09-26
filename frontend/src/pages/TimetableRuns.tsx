import { useState, useEffect, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { timetableApi, departmentsApi, yearsApi, sectionsApi } from '../api/client';
import { TimetableRun, Department, AcademicYear, Section } from '../types';
import { Calendar, CheckCircle, XCircle, RefreshCw, Clock, Star, AlertTriangle, ChevronDown, ChevronUp, Trash2 } from 'lucide-react';
import { useInstitutionTimezone, formatInTimezone } from '../hooks/useInstitutionTimezone';
import { fuzzyMatches } from '../utils/fuzzySearch';

function getWarnings(run: TimetableRun): string[] {
  return run.solver_output?.warnings || [];
}

export function TimetableRuns() {
  const [runs, setRuns] = useState<TimetableRun[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [years, setYears] = useState<AcademicYear[]>([]);
  const [sections, setSections] = useState<Section[]>([]);
  const [loading, setLoading] = useState(true);
  const [publishing, setPublishing] = useState<number | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);
  const [statusFilter, setStatusFilter] = useState('completed');
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');
  const [search, setSearch] = useState('');
  const [expandedWarnings, setExpandedWarnings] = useState<Set<number>>(new Set());
  const [error, setError] = useState('');
  const timezone = useInstitutionTimezone();

  useEffect(() => {
    fetchRuns();
    departmentsApi.list().then((res) => setDepartments(res.data)).catch(() => {});
    yearsApi.list().then((res) => setYears(res.data)).catch(() => {});
    sectionsApi.list().then((res) => setSections(res.data)).catch(() => {});
  }, []);

  const fetchRuns = async () => {
    try {
      const response = await timetableApi.listRuns();
      setRuns(response.data);
    } catch (error) {
      console.error('Failed to fetch runs:', error);
    } finally {
      setLoading(false);
    }
  };

  const runLabel = (run: TimetableRun) => `Timetable — ${formatInTimezone(run.created_at, timezone)}`;

  // Phase 4.4: search what's actually on screen - label, status,
  // department, year and section names - instead of an id + free-text
  // pair that never contains the word the admin typed ("run").
  const searchableText = (run: TimetableRun) => [
    runLabel(run), `#${run.id}`, run.status,
    departments.find((d) => d.id === run.department_id)?.name,
    ...(run.year_ids || []).map((id) => years.find((y) => y.id === id)?.name),
    ...(run.section_ids || []).map((id) => sections.find((s) => s.id === id)?.name),
    run.change_summary, run.llm_explanation,
  ].filter(Boolean).join(' ');

  const filteredRuns = useMemo(() => runs.filter((run) => {
    if (statusFilter !== 'all' && run.status !== statusFilter) return false;
    const created = new Date(run.created_at);
    if (fromDate && created < new Date(`${fromDate}T00:00:00`)) return false;
    if (toDate && created > new Date(`${toDate}T23:59:59`)) return false;
    if (search && !fuzzyMatches(searchableText(run), search)) return false;
    return true;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [runs, statusFilter, fromDate, toDate, search, departments, years, sections, timezone]);

  const handlePublish = async (id: number) => {
    setPublishing(id);
    try {
      await timetableApi.publish(id);
      await fetchRuns();
    } catch (error) {
      console.error('Publish failed:', error);
    } finally {
      setPublishing(null);
    }
  };

  const handleDelete = async (run: TimetableRun) => {
    if (!window.confirm(`Delete ${runLabel(run)}? This can't be undone.`)) return;
    setDeleting(run.id);
    setError('');
    try {
      await timetableApi.deleteRun(run.id);
      await fetchRuns();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not delete this timetable.');
    } finally {
      setDeleting(null);
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle size={20} className="text-green-500" />;
      case 'failed':
        return <XCircle size={20} className="text-red-500" />;
      case 'solving':
        return <RefreshCw size={20} className="text-blue-500 animate-spin" />;
      default:
        return <Clock size={20} className="text-gray-400" />;
    }
  };

  const getStatusColor = (run: TimetableRun) => {
    switch (run.status) {
      case 'completed':
        return getWarnings(run).length > 0 ? 'bg-amber-100 text-amber-800' : 'bg-green-100 text-green-800';
      case 'failed':
        return 'bg-red-100 text-red-800';
      case 'solving':
        return 'bg-blue-100 text-blue-800';
      default:
        return 'bg-gray-100 text-gray-600';
    }
  };

  const toggleWarnings = (runId: number) => {
    setExpandedWarnings((current) => {
      const next = new Set(current);
      if (next.has(runId)) next.delete(runId); else next.add(runId);
      return next;
    });
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <RefreshCw size={32} className="animate-spin text-blue-600" />
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold text-gray-900">Timetables</h1>
        <Link
          to="/"
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          Generate a new one
        </Link>
      </div>

      {error && <p className="mb-4 rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">{error}</p>}

      <div className="mb-6 grid grid-cols-1 gap-3 rounded-lg border border-gray-200 bg-white p-4 md:grid-cols-5">
        <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search by label, status, department, year, or section" className="rounded-lg border border-gray-300 px-3 py-2 text-sm md:col-span-2" />
        <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="rounded-lg border border-gray-300 px-3 py-2 text-sm">
          <option value="completed">Completed only</option>
          <option value="all">All statuses</option>
          <option value="solving">In progress</option>
          <option value="failed">Failed only</option>
        </select>
        <input type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} aria-label="Created from" className="rounded-lg border border-gray-300 px-3 py-2 text-sm" />
        <input type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} aria-label="Created to" className="rounded-lg border border-gray-300 px-3 py-2 text-sm" />
      </div>

      {filteredRuns.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-lg border border-gray-200">
          <Calendar size={48} className="mx-auto text-gray-400 mb-4" />
          <p className="text-gray-500">No runs match these filters. Try “All statuses” to inspect failed runs.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {filteredRuns.map((run) => (
            <div key={run.id} className="bg-white rounded-lg border border-gray-200 p-4 hover:shadow-md transition-shadow">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  {getStatusIcon(run.status)}
                  <div>
                    <h3 className="font-semibold text-gray-900 flex items-center gap-2">
                      {runLabel(run)}
                      <span className="text-xs font-normal text-gray-400">#{run.id}</span>
                      {run.is_published && (
                        <span className="flex items-center gap-1 text-xs font-medium text-green-700 bg-green-100 px-2 py-0.5 rounded-full">
                          <Star size={12} /> Published
                        </span>
                      )}
                    </h3>
                    <p className="text-sm text-gray-600">
                      {departments.find((d) => d.id === run.department_id)?.name}
                      {run.parent_run_id && <span className="text-gray-400"> · edited from run #{run.parent_run_id}</span>}
                    </p>
                    {run.change_summary && (
                      <p className="text-sm text-gray-500 mt-0.5">{run.change_summary}</p>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`px-3 py-1 rounded-full text-xs font-medium ${getStatusColor(run)}`}>
                    {run.status}
                  </span>
                  {!run.is_published && (
                    <button
                      onClick={() => handleDelete(run)}
                      disabled={deleting === run.id}
                      title="Delete this timetable"
                      className="p-1.5 text-red-500 hover:bg-red-50 rounded-lg disabled:opacity-50"
                    >
                      <Trash2 size={16} />
                    </button>
                  )}
                </div>
              </div>

              {run.status === 'completed' && (
                <div className="mt-3 flex items-center gap-4">
                  <Link
                    to={`/runs/${run.id}`}
                    className="text-blue-600 hover:text-blue-800 text-sm font-medium"
                  >
                    View Timetable →
                  </Link>
                  <Link
                    to={`/runs/${run.id}/versions`}
                    className="text-gray-500 hover:text-gray-700 text-sm font-medium"
                  >
                    Version History
                  </Link>
                  {!run.is_published && (
                    <button
                      onClick={() => handlePublish(run.id)}
                      disabled={publishing === run.id}
                      className="text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50 px-3 py-1 rounded-lg"
                    >
                      {publishing === run.id ? 'Publishing...' : 'Publish'}
                    </button>
                  )}
                </div>
              )}

              {run.status === 'completed' && getWarnings(run).length > 0 && (
                <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3">
                  <button
                    type="button"
                    onClick={() => toggleWarnings(run.id)}
                    className="flex w-full items-center justify-between text-sm font-medium text-amber-800"
                  >
                    <span className="flex items-center gap-2">
                      <AlertTriangle size={16} />
                      {getWarnings(run).length} thing{getWarnings(run).length === 1 ? '' : 's'} were skipped
                    </span>
                    {expandedWarnings.has(run.id) ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                  </button>
                  {expandedWarnings.has(run.id) && (
                    <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-amber-800">
                      {getWarnings(run).map((warning, index) => (
                        <li key={index}>{warning}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              {run.status === 'failed' && run.llm_explanation && (
                <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg">
                  <p className="text-sm text-red-700 line-clamp-3">{run.llm_explanation}</p>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
