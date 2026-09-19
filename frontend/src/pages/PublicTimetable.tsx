import { useEffect, useState } from 'react';
import { publicApi } from '../api/client';

type ViewType = 'sections' | 'faculty' | 'rooms';

interface Option {
  id: string;
  name: string;
}

export function PublicTimetable() {
  const [viewType, setViewType] = useState<ViewType>('sections');
  const [options, setOptions] = useState<Option[]>([]);
  const [selectedId, setSelectedId] = useState<string>('');
  const [grid, setGrid] = useState<Record<string, Record<string, any>> | null>(null);
  const [free, setFree] = useState<Record<string, number[]> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSelectedId('');
    setGrid(null);
    setError(null);
    const load = async () => {
      try {
        if (viewType === 'sections') {
          const res = await publicApi.sections();
          setOptions(res.data.sections.map((s: any) => ({ id: s.section_id, name: s.section_name })));
        } else if (viewType === 'faculty') {
          const res = await publicApi.faculty();
          setOptions(res.data.faculty.map((f: any) => ({ id: f.teacher_id, name: f.teacher_name })));
        } else {
          const res = await publicApi.rooms();
          setOptions(res.data.rooms.map((r: any) => ({ id: r.room_id, name: r.room_name })));
        }
      } catch (err: any) {
        setError(err.response?.data?.detail || 'No published timetable is available yet.');
      }
    };
    load();
  }, [viewType]);

  useEffect(() => {
    if (!selectedId) return;
    const load = async () => {
      try {
        setError(null);
        if (viewType === 'sections') {
          const res = await publicApi.section(selectedId);
          setGrid(res.data.grid);
          setFree(null);
        } else if (viewType === 'faculty') {
          const res = await publicApi.facultyMember(selectedId);
          setGrid(res.data.grid);
          setFree(null);
        } else {
          const res = await publicApi.room(selectedId);
          setGrid(res.data.occupied);
          setFree(res.data.free);
        }
      } catch (err: any) {
        setError(err.response?.data?.detail || 'Could not load timetable.');
      }
    };
    load();
  }, [selectedId, viewType]);

  const days = grid ? Object.keys(grid) : [];
  const periods = grid
    ? Array.from(new Set(days.flatMap((d) => Object.keys(grid[d]).map(Number)))).sort((a, b) => a - b)
    : [];

  return (
    <div className="min-h-screen bg-gray-50 p-6 lg:p-8">
      <div className="max-w-5xl mx-auto space-y-6">
        <h1 className="text-2xl font-bold text-blue-600">Timetable Lookup</h1>
        <p className="text-sm text-gray-500">
          Public read-only view — no login required. Powered by <code>/api/public/timetables</code>.
        </p>

        <div className="flex gap-4 items-end">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">View</label>
            <select
              className="border border-gray-300 rounded-md px-3 py-2 text-sm"
              value={viewType}
              onChange={(e) => setViewType(e.target.value as ViewType)}
            >
              <option value="sections">Section / Class</option>
              <option value="faculty">Faculty</option>
              <option value="rooms">Room</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Select</label>
            <select
              className="border border-gray-300 rounded-md px-3 py-2 text-sm min-w-[200px]"
              value={selectedId}
              onChange={(e) => setSelectedId(e.target.value)}
            >
              <option value="">-- choose --</option>
              {options.map((o) => (
                <option key={o.id} value={o.id}>{o.name}</option>
              ))}
            </select>
          </div>
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}

        {grid && periods.length > 0 && (
          <div className="overflow-x-auto bg-white rounded-lg border border-gray-200">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="bg-gray-100">
                  <th className="px-3 py-2 text-left">Day \ Period</th>
                  {periods.map((p) => (
                    <th key={p} className="px-3 py-2 text-left">P{p}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {days.map((day) => (
                  <tr key={day} className="border-t border-gray-100">
                    <td className="px-3 py-2 font-medium">{day}</td>
                    {periods.map((p) => {
                      const cell = grid[day]?.[p];
                      const isFree = free && free[day]?.includes(p);
                      return (
                        <td key={p} className="px-3 py-2 align-top">
                          {cell ? (
                            <div>
                              <div className="font-medium">{cell.subject_name || cell.subject_id}</div>
                              <div className="text-xs text-gray-500">
                                {cell.teacher_name || cell.teacher_id} · {cell.room_name || cell.room_id}
                              </div>
                              {cell.section_name && <div className="text-xs text-gray-400">{cell.section_name}</div>}
                            </div>
                          ) : isFree ? (
                            <span className="text-xs text-green-600">Free</span>
                          ) : (
                            <span className="text-xs text-gray-300">—</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
