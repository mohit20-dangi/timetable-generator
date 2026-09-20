import { useState, useEffect } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { timetableApi, sectionsApi, subjectsApi, teachersApi, roomsApi, constraintsApi } from '../api/client';
import { TimetableEntry, Section, Subject, Teacher, Room, TimetableRun } from '../types';
import { ChevronLeft, Download, Users, BookOpen, MapPin, Star, History, GitBranch, CalendarPlus } from 'lucide-react';
import { EditEntryModal } from '../components/EditEntryModal';
import { DAYS, DAY_LABELS, DEFAULT_SLOTS, ScheduleSlot, timeLabel } from '../utils/schedule';

export function TimetableViewer() {
  const { runId } = useParams<{ runId: string }>();
  const [entries, setEntries] = useState<TimetableEntry[]>([]);
  const [run, setRun] = useState<TimetableRun | null>(null);
  const [sections, setSections] = useState<Record<string, Section>>({});
  const [subjects, setSubjects] = useState<Record<string, Subject>>({});
  const [teachers, setTeachers] = useState<Record<string, Teacher>>({});
  const [rooms, setRooms] = useState<Record<string, Room>>({});
  const [batchToSection, setBatchToSection] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState<'section' | 'teacher' | 'room'>('section');
  const [selectedEntity, setSelectedEntity] = useState<string>('');
  const [publishing, setPublishing] = useState(false);
  const [editingEntry, setEditingEntry] = useState<TimetableEntry | null>(null);
  const [alternatives, setAlternatives] = useState<any[]>([]);
  const [selectedAlternative, setSelectedAlternative] = useState(1);
  const [validation, setValidation] = useState<{ valid: boolean; issues?: Array<{ message: string }> } | null>(null);
  const [usingAlternative, setUsingAlternative] = useState(false);
  const [scheduleSlots, setScheduleSlots] = useState<ScheduleSlot[]>(DEFAULT_SLOTS);
  const navigate = useNavigate();

  useEffect(() => {
    fetchData();
  }, [runId]);

  const fetchData = async () => {
    try {
      const [entriesRes, runRes, sectionsRes, subjectsRes, teachersRes, roomsRes, alternativesRes, validationRes, slotsRes] = await Promise.all([
        timetableApi.getEntries(parseInt(runId!)),
        timetableApi.getRun(parseInt(runId!)),
        sectionsApi.list(),
        subjectsApi.list(),
        teachersApi.list(),
        roomsApi.list(),
        timetableApi.getAlternatives(parseInt(runId!)),
        timetableApi.validate(parseInt(runId!)),
        constraintsApi.listTimeSlots()
      ]);
      
      setEntries(entriesRes.data);
      setRun(runRes.data);
      setAlternatives(alternativesRes.data.alternatives || []);
      setSelectedAlternative(1);
      setValidation(validationRes.data);
      setScheduleSlots(slotsRes.data.length ? slotsRes.data : DEFAULT_SLOTS);
      
      const secMap: Record<string, Section> = {};
      sectionsRes.data.forEach((s: Section) => { secMap[s.id] = s; });
      setSections(secMap);
      
      const subjMap: Record<string, Subject> = {};
      subjectsRes.data.forEach((s: Subject) => { subjMap[s.id] = s; });
      setSubjects(subjMap);
      
      const teachMap: Record<string, Teacher> = {};
      teachersRes.data.forEach((t: Teacher) => { teachMap[t.id] = t; });
      setTeachers(teachMap);
      
      const roomMap: Record<string, Room> = {};
      roomsRes.data.forEach((r: Room) => { roomMap[r.id] = r; });
      setRooms(roomMap);

      const batchesBySection = await Promise.all(
        sectionsRes.data.map((section: Section) => constraintsApi.getLabBatches(section.id))
      );
      const batchMap: Record<string, string> = {};
      batchesBySection.forEach((response, index) => {
        response.data.forEach((batch: { id: string }) => {
          batchMap[batch.id] = sectionsRes.data[index].id;
        });
      });
      setBatchToSection(batchMap);
      
      // Set default selected entity
      const firstSection = Object.keys(secMap)[0];
      if (firstSection) setSelectedEntity(firstSection);
    } catch (error) {
      console.error('Failed to fetch data:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleAlternativeChange = async (rank: number) => {
    setSelectedAlternative(rank);
    try {
      if (rank === 1) {
        const response = await timetableApi.getEntries(parseInt(runId!));
        setEntries(response.data);
      } else {
        const response = await timetableApi.getAlternative(parseInt(runId!), rank);
        setEntries(response.data.entries || []);
      }
    } catch (error) {
      console.error('Failed to load timetable alternative:', error);
    }
  };

  const handleUseAlternative = async () => {
    setUsingAlternative(true);
    try {
      const response = await timetableApi.useAlternative(parseInt(runId!), selectedAlternative);
      navigate(`/runs/${response.data.id}`);
    } catch (error) {
      console.error('Failed to use timetable alternative:', error);
    } finally {
      setUsingAlternative(false);
    }
  };

  const getSubjectName = (subjectId: string) => {
    return subjects[subjectId]?.name || subjectId;
  };

  const getSubjectType = (subjectId: string) => {
    return subjects[subjectId]?.type || 'unknown';
  };

  const getTeacherName = (teacherId: string) => {
    return teachers[teacherId]?.name || teacherId;
  };

  const getRoomName = (roomId: string) => {
    return rooms[roomId]?.name || roomId;
  };

  const periodNumbers = [...new Set(scheduleSlots.map((slot) => slot.period_index))].sort((a, b) => a - b);
  const slotMap = new Map(scheduleSlots.map((slot) => [`${slot.day}-${slot.period_index}`, slot]));

  const getSubjectColor = (type: string) => {
    switch (type) {
      case 'theory':
        return 'bg-blue-100 text-blue-800 border-blue-200';
      case 'lab':
        return 'bg-green-100 text-green-800 border-green-200';
      case 'tutorial':
        return 'bg-purple-100 text-purple-800 border-purple-200';
      default:
        return 'bg-gray-100 text-gray-800 border-gray-200';
    }
  };

  const getEntriesForEntity = (entityId: string) => {
    return entries.filter(entry => {
      if (viewMode === 'section') {
        return entry.section_id === entityId
          || entry.batch_id === entityId
          || (!!entry.batch_id && batchToSection[entry.batch_id] === entityId);
      } else if (viewMode === 'teacher') {
        return entry.teacher_id === entityId;
      } else {
        return entry.room_id === entityId;
      }
    });
  };

  const getEntityOptions = () => {
    if (viewMode === 'section') {
      return Object.values(sections).map(s => ({ value: s.id, label: s.name }));
    } else if (viewMode === 'teacher') {
      return Object.values(teachers).map(t => ({ value: t.id, label: t.name }));
    } else {
      return Object.values(rooms).map(r => ({ value: r.id, label: r.name }));
    }
  };

  const changeViewMode = (mode: 'section' | 'teacher' | 'room') => {
    setViewMode(mode);
    const options = mode === 'section'
      ? Object.values(sections).map((section) => ({ value: section.id }))
      : mode === 'teacher'
        ? Object.values(teachers).map((teacher) => ({ value: teacher.id }))
        : Object.values(rooms).map((room) => ({ value: room.id }));
    setSelectedEntity(options[0]?.value || '');
  };

  const handleExport = async (format: string) => {
    try {
      const response = await timetableApi.export(parseInt(runId!), format, viewMode, selectedEntity || undefined);
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.download = `timetable_run_${runId}.${format}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Export failed:', error);
    }
  };

  const handlePublish = async () => {
    setPublishing(true);
    try {
      await timetableApi.publish(parseInt(runId!));
      await fetchData();
    } catch (error) {
      console.error('Publish failed:', error);
    } finally {
      setPublishing(false);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  const entityEntries = getEntriesForEntity(selectedEntity);
  const entityOptions = getEntityOptions();

  return (
    <div className="max-w-7xl mx-auto">
      <div className="flex justify-between items-center mb-6">
        <div className="flex items-center gap-4">
          <Link to="/runs" className="text-gray-600 hover:text-gray-900">
            <ChevronLeft size={20} />
          </Link>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            Timetable Run #{runId}
            {run?.is_published && (
              <span className="flex items-center gap-1 text-xs font-medium text-green-700 bg-green-100 px-2 py-0.5 rounded-full">
                <Star size={12} /> Published
              </span>
            )}
          </h1>
        </div>
        <div className="flex gap-2">
          <Link
            to={`/runs/${runId}/versions`}
            className="flex items-center gap-2 px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors text-sm"
          >
            <History size={18} />
            Versions
          </Link>
          {run && !run.is_published && (
            <button
              onClick={handlePublish}
              disabled={publishing}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors text-sm"
            >
              <Star size={18} />
              {publishing ? 'Publishing...' : 'Publish'}
            </button>
          )}
          <button
            onClick={() => handleExport('xlsx')}
            className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors"
          >
            <Download size={20} />
            Export Excel
          </button>
          <button
            onClick={() => handleExport('pdf')}
            className="flex items-center gap-2 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors"
          >
            <Download size={20} />
            Export PDF
          </button>
          <button
            onClick={() => handleExport('ics')}
            title="Subscribe in Google Calendar, Outlook, or Apple Calendar"
            className="flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors"
          >
            <CalendarPlus size={20} />
            Export Calendar
          </button>
        </div>
      </div>

      {run && !run.is_published && (
        <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-4">
          This run isn't published yet - students and faculty won't see it under "My Timetable" until you publish it.
        </p>
      )}

      {alternatives.length > 1 && (
        <div className="mb-5 flex flex-wrap items-center gap-3 rounded-lg border border-blue-100 bg-blue-50 p-3">
          <GitBranch size={20} className="text-blue-700" />
          <label htmlFor="alternative-select" className="text-sm font-medium text-blue-900">Alternative timetable</label>
          <select
            id="alternative-select"
            value={selectedAlternative}
            onChange={(event) => handleAlternativeChange(parseInt(event.target.value, 10))}
            className="px-3 py-1.5 border border-blue-200 rounded-lg bg-white text-sm text-gray-800"
          >
            {alternatives.map((alternative) => (
              <option key={alternative.rank} value={alternative.rank}>
                #{alternative.rank} · objective {Number(alternative.objective_value || 0).toFixed(0)}
              </option>
            ))}
          </select>
          <span className="text-xs text-blue-800">
            {alternatives.find((alternative) => alternative.rank === selectedAlternative)?.diversity_from_previous || 0} placement changes from the previous option
          </span>
          <button
            type="button"
            onClick={handleUseAlternative}
            disabled={usingAlternative}
            className="ml-auto rounded-lg bg-blue-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-800 disabled:opacity-50"
          >
            {usingAlternative ? 'Creating version...' : 'Use this alternative'}
          </button>
        </div>
      )}

      {validation && (
        <div className={`mb-5 rounded-lg border p-3 text-sm ${validation.valid ? 'border-green-200 bg-green-50 text-green-800' : 'border-red-200 bg-red-50 text-red-800'}`}>
          <span className="font-medium">Independent validation: {validation.valid ? 'passed' : 'failed'}</span>
          {!validation.valid && validation.issues?.slice(0, 3).map((issue) => (
            <p key={issue.message} className="mt-1">{issue.message}</p>
          ))}
        </div>
      )}

      {/* View mode selector */}
      <div className="flex gap-2 mb-6">
        <button
          onClick={() => changeViewMode('section')}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
            viewMode === 'section'
              ? 'bg-blue-600 text-white'
              : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
          }`}
        >
          <Users size={20} />
          By Section
        </button>
        <button
          onClick={() => changeViewMode('teacher')}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
            viewMode === 'teacher'
              ? 'bg-blue-600 text-white'
              : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
          }`}
        >
          <BookOpen size={20} />
          By Teacher
        </button>
        <button
          onClick={() => changeViewMode('room')}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
            viewMode === 'room'
              ? 'bg-blue-600 text-white'
              : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
          }`}
        >
          <MapPin size={20} />
          By Room
        </button>
      </div>

      {/* Entity selector */}
      <div className="mb-6">
        <label className="block text-sm font-medium text-gray-700 mb-2">
          Select {viewMode === 'section' ? 'Section' : viewMode === 'teacher' ? 'Teacher' : 'Room'}
        </label>
        <select
          value={selectedEntity}
          onChange={(e) => setSelectedEntity(e.target.value)}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        >
          {entityOptions.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </div>

      {/* Timetable grid */}
      <div className="bg-white rounded-lg border border-gray-200 overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr className="bg-gray-100">
              <th className="px-4 py-2 text-left font-medium text-gray-700">Time</th>
              {DAYS.map((day) => (
                <th key={day} className="px-4 py-2 text-center font-medium text-gray-700">{DAY_LABELS[day]}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {periodNumbers.map((period) => (
              <tr key={period} className="border-b border-gray-200">
                <td className="px-4 py-2 font-medium text-gray-600 whitespace-nowrap">
                  <div>Period {period}</div>
                  <div className="text-xs text-gray-400">{timeLabel(scheduleSlots.find((slot) => slot.period_index === period))}</div>
                </td>
                {DAYS.map((day) => {
                  const slot = slotMap.get(`${day}-${period}`);
                  const cellEntries = entityEntries.filter(
                    e => e.day === day && e.period === period
                  );
                  return (
                    <td key={`${day}-${period}`} title={slot ? timeLabel(slot) : 'No class slot configured'} className="p-1 border border-gray-100 min-h-[60px]">
                      {cellEntries.length ? (
                        <div className="space-y-1">
                          {cellEntries.map((entry) => (
                            <div
                              key={entry.id}
                              onClick={() => viewMode === 'section' && setEditingEntry(entry)}
                              className={`p-2 rounded border text-xs ${getSubjectColor(getSubjectType(entry.subject_id))} ${viewMode === 'section' ? 'cursor-pointer hover:ring-2 hover:ring-blue-400' : ''}`}
                              title={viewMode === 'section' ? 'Click to move this class' : undefined}
                            >
                              <div className="font-medium">{getSubjectName(entry.subject_id)}</div>
                              {entry.batch_id && <div className="text-gray-600">Batch: {entry.batch_id}</div>}
                              <div className="text-gray-600">{getTeacherName(entry.teacher_id)}</div>
                              <div className="text-gray-600">{getRoomName(entry.room_id)}</div>
                            </div>
                          ))}
                        </div>
                      ) : slot ? (
                        <div className="h-full flex items-center justify-center text-gray-300 text-xs">
                          Free
                        </div>
                      ) : <div className="h-full bg-gray-50" />}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Legend */}
      <div className="mt-6 flex gap-4">
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 bg-blue-100 border border-blue-200 rounded"></div>
          <span className="text-sm text-gray-600">Theory</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 bg-green-100 border border-green-200 rounded"></div>
          <span className="text-sm text-gray-600">Lab</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 bg-purple-100 border border-purple-200 rounded"></div>
          <span className="text-sm text-gray-600">Tutorial</span>
        </div>
      </div>

      {viewMode === 'section' && (
        <p className="text-xs text-gray-400 mt-4">Click any class above to move it to a different day/period.</p>
      )}

      {editingEntry && (
        <EditEntryModal
          runId={parseInt(runId!)}
          entry={editingEntry}
          subjectName={getSubjectName(editingEntry.subject_id)}
          onClose={() => setEditingEntry(null)}
        />
      )}
    </div>
  );
}
