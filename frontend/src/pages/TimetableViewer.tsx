import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { timetableApi, sectionsApi, subjectsApi, teachersApi, roomsApi } from '../api/client';
import { TimetableEntry, Section, Subject, Teacher, Room } from '../types';
import { ChevronLeft, Download, Users, BookOpen, MapPin } from 'lucide-react';

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const PERIODS = [1, 2, 3, 4, 5, 6, 7, 8];

export function TimetableViewer() {
  const { runId } = useParams<{ runId: string }>();
  const [entries, setEntries] = useState<TimetableEntry[]>([]);
  const [sections, setSections] = useState<Record<string, Section>>({});
  const [subjects, setSubjects] = useState<Record<string, Subject>>({});
  const [teachers, setTeachers] = useState<Record<string, Teacher>>({});
  const [rooms, setRooms] = useState<Record<string, Room>>({});
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState<'section' | 'teacher' | 'room'>('section');
  const [selectedEntity, setSelectedEntity] = useState<string>('');

  useEffect(() => {
    fetchData();
  }, [runId]);

  const fetchData = async () => {
    try {
      const [entriesRes, sectionsRes, subjectsRes, teachersRes, roomsRes] = await Promise.all([
        timetableApi.getEntries(parseInt(runId!)),
        sectionsApi.list(),
        subjectsApi.list(),
        teachersApi.list(),
        roomsApi.list()
      ]);
      
      setEntries(entriesRes.data);
      
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
      
      // Set default selected entity
      const firstSection = Object.keys(secMap)[0];
      if (firstSection) setSelectedEntity(firstSection);
    } catch (error) {
      console.error('Failed to fetch data:', error);
    } finally {
      setLoading(false);
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
        return entry.section_id === entityId || entry.batch_id === entityId;
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

  const handleExport = async (format: string) => {
    try {
      const response = await timetableApi.export(parseInt(runId!), format);
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
          <h1 className="text-2xl font-bold text-gray-900">Timetable Run #{runId}</h1>
        </div>
        <div className="flex gap-2">
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
        </div>
      </div>

      {/* View mode selector */}
      <div className="flex gap-2 mb-6">
        <button
          onClick={() => setViewMode('section')}
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
          onClick={() => setViewMode('teacher')}
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
          onClick={() => setViewMode('room')}
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
              <th className="px-4 py-2 text-left font-medium text-gray-700">Period</th>
              {DAYS.map((day) => (
                <th key={day} className="px-4 py-2 text-center font-medium text-gray-700">{day}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {PERIODS.map((period) => (
              <tr key={period} className="border-b border-gray-200">
                <td className="px-4 py-2 font-medium text-gray-600">Period {period}</td>
                {DAYS.map((day) => {
                  const entry = entityEntries.find(
                    e => e.day === day && e.period === period
                  );
                  return (
                    <td key={`${day}-${period}`} className="p-1 border border-gray-100 min-h-[60px]">
                      {entry ? (
                        <div className={`p-2 rounded border text-xs ${getSubjectColor(getSubjectType(entry.subject_id))}`}>
                          <div className="font-medium">{getSubjectName(entry.subject_id)}</div>
                          <div className="text-gray-600">{getTeacherName(entry.teacher_id)}</div>
                          <div className="text-gray-600">{getRoomName(entry.room_id)}</div>
                        </div>
                      ) : (
                        <div className="h-full flex items-center justify-center text-gray-300 text-xs">
                          Free
                        </div>
                      )}
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
    </div>
  );
}