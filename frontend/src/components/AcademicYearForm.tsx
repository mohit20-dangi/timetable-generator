import { useState, useEffect } from 'react';
import { yearsApi, sectionsApi } from '../api/client';
import { AcademicYear, Section } from '../types';
import { useDepartment } from '../context/DepartmentContext';
import { Plus, Edit, Trash2, Save, X, Users } from 'lucide-react';

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

const emptyForm = () => ({
  id: '',
  name: '',
  num_sections: 1,
  default_section_strength: 60,
  lunch_windows: {} as Record<string, [string, string]>,
});

export function AcademicYearForm() {
  const { departmentId } = useDepartment();
  const [years, setYears] = useState<AcademicYear[]>([]);
  const [sectionCounts, setSectionCounts] = useState<Record<string, number>>({});
  const [showForm, setShowForm] = useState(false);
  const [editingYear, setEditingYear] = useState<AcademicYear | null>(null);
  const [formData, setFormData] = useState(emptyForm());
  const [error, setError] = useState('');

  const fetchYears = async () => {
    try {
      const response = await yearsApi.list();
      const list = departmentId ? response.data.filter((y: AcademicYear) => y.department_id === departmentId) : response.data;
      setYears(list);
      const sectionsResponse = await sectionsApi.list();
      const counts: Record<string, number> = {};
      for (const section of sectionsResponse.data as Section[]) {
        counts[section.year_id] = (counts[section.year_id] || 0) + 1;
      }
      setSectionCounts(counts);
    } catch (err) {
      console.error('Failed to fetch years:', err);
    }
  };

  useEffect(() => {
    fetchYears();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [departmentId]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    const payload = { ...formData, department_id: departmentId || null };
    try {
      if (editingYear) {
        await yearsApi.update(editingYear.id, payload);
      } else {
        await yearsApi.create(payload);
      }
      setShowForm(false);
      setEditingYear(null);
      setFormData(emptyForm());
      fetchYears();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not save the academic year.');
    }
  };

  const handleEdit = (year: AcademicYear) => {
    setEditingYear(year);
    setFormData({
      id: year.id,
      name: year.name,
      num_sections: year.num_sections,
      default_section_strength: year.default_section_strength ?? 60,
      lunch_windows: year.lunch_windows || {},
    });
    setShowForm(true);
  };

  const handleDelete = async (id: string) => {
    if (window.confirm('Are you sure you want to delete this academic year?')) {
      try {
        await yearsApi.delete(id);
        fetchYears();
      } catch (err) {
        console.error('Failed to delete year:', err);
      }
    }
  };

  const handleCreateRemaining = async (year: AcademicYear) => {
    setError('');
    try {
      await yearsApi.createRemainingSections(year.id);
      fetchYears();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not create the remaining sections.');
    }
  };

  const toggleLunchDay = (day: string, enabled: boolean) => {
    const next = { ...formData.lunch_windows };
    if (enabled) {
      next[day] = ['12:00', '13:00'];
    } else {
      delete next[day];
    }
    setFormData({ ...formData, lunch_windows: next });
  };

  const selectAllLunchDays = () => {
    const next = { ...formData.lunch_windows };
    for (const day of DAYS.slice(0, 6)) {
      if (!(day in next)) next[day] = ['12:00', '13:00'];
    }
    setFormData({ ...formData, lunch_windows: next });
  };

  const clearAllLunchDays = () => {
    setFormData({ ...formData, lunch_windows: {} });
  };

  const setLunchTime = (day: string, index: 0 | 1, value: string) => {
    const current = formData.lunch_windows[day] || ['12:00', '13:00'];
    const next: [string, string] = index === 0 ? [value, current[1]] : [current[0], value];
    setFormData({ ...formData, lunch_windows: { ...formData.lunch_windows, [day]: next } });
  };

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold">Academic Years</h3>
        <button
          onClick={() => {
            setShowForm(true);
            setEditingYear(null);
            setFormData(emptyForm());
          }}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          <Plus size={20} />
          Add Year
        </button>
      </div>

      {error && <p className="mb-4 rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">{error}</p>}

      {showForm && (
        <div className="mb-6 p-4 border border-gray-200 rounded-lg bg-gray-50">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Year ID</label>
                <input
                  type="text"
                  value={formData.id}
                  onChange={(e) => setFormData({ ...formData, id: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="e.g., y1"
                  required
                  disabled={!!editingYear}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Year Name</label>
                <input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="e.g., 1st Year"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Number of Sections (target)</label>
                <input
                  type="number"
                  min="1"
                  value={formData.num_sections}
                  onChange={(e) => setFormData({ ...formData, num_sections: parseInt(e.target.value) || 1 })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Default section strength</label>
                <input
                  type="number"
                  min="1"
                  value={formData.default_section_strength}
                  onChange={(e) => setFormData({ ...formData, default_section_strength: parseInt(e.target.value) || 1 })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
                <p className="text-xs text-gray-500 mt-1">Used when sections are auto-created for this year.</p>
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="block text-sm font-medium text-gray-700">Lunch break, per day</label>
                <div className="flex gap-3">
                  <button type="button" onClick={selectAllLunchDays} className="text-xs text-blue-600 hover:text-blue-800">
                    Select all
                  </button>
                  <button type="button" onClick={clearAllLunchDays} className="text-xs text-gray-500 hover:text-gray-700">
                    Clear all
                  </button>
                </div>
              </div>
              <p className="text-xs text-gray-500 mb-2">
                Leave a day unchecked if it has no lunch break (e.g. a day that runs a class straight through).
              </p>
              <div className="space-y-2">
                {DAYS.slice(0, 6).map((day) => {
                  const enabled = day in formData.lunch_windows;
                  const window = formData.lunch_windows[day] || ['12:00', '13:00'];
                  return (
                    <div key={day} className="flex items-center gap-3">
                      <label className="flex items-center gap-2 w-24">
                        <input
                          type="checkbox"
                          checked={enabled}
                          onChange={(e) => toggleLunchDay(day, e.target.checked)}
                          className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                        />
                        <span className="text-sm text-gray-700">{day}</span>
                      </label>
                      <input
                        type="time"
                        value={window[0]}
                        disabled={!enabled}
                        onChange={(e) => setLunchTime(day, 0, e.target.value)}
                        className="px-3 py-2 border border-gray-300 rounded-lg disabled:bg-gray-100"
                      />
                      <span className="text-gray-500">to</span>
                      <input
                        type="time"
                        value={window[1]}
                        disabled={!enabled}
                        onChange={(e) => setLunchTime(day, 1, e.target.value)}
                        className="px-3 py-2 border border-gray-300 rounded-lg disabled:bg-gray-100"
                      />
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="flex gap-2">
              <button
                type="submit"
                className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors"
              >
                <Save size={20} />
                {editingYear ? 'Update' : 'Save'}
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowForm(false);
                  setEditingYear(null);
                }}
                className="flex items-center gap-2 px-4 py-2 bg-gray-300 text-gray-700 rounded-lg hover:bg-gray-400 transition-colors"
              >
                <X size={20} />
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr className="bg-gray-100">
              <th className="text-left px-4 py-2 font-medium text-gray-700">ID</th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">Name</th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">Sections</th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">Lunch Days</th>
              <th className="text-right px-4 py-2 font-medium text-gray-700">Actions</th>
            </tr>
          </thead>
          <tbody>
            {years.map((year) => {
              const created = sectionCounts[year.id] || 0;
              return (
                <tr key={year.id} className="border-b border-gray-200">
                  <td className="px-4 py-2">{year.id}</td>
                  <td className="px-4 py-2">{year.name}</td>
                  <td className="px-4 py-2">
                    {created} of {year.num_sections}
                    {created < year.num_sections && (
                      <button
                        onClick={() => handleCreateRemaining(year)}
                        className="ml-2 inline-flex items-center gap-1 text-xs text-blue-700 bg-blue-50 hover:bg-blue-100 rounded px-2 py-1"
                      >
                        <Users size={12} /> Create the remaining {year.num_sections - created} for me
                      </button>
                    )}
                  </td>
                  <td className="px-4 py-2">
                    {Object.keys(year.lunch_windows || {}).length > 0
                      ? Object.entries(year.lunch_windows).map(([day, w]) => `${day} ${w[0]}-${w[1]}`).join(', ')
                      : 'Not set'}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button
                      onClick={() => handleEdit(year)}
                      className="p-1 text-blue-600 hover:bg-blue-100 rounded"
                    >
                      <Edit size={16} />
                    </button>
                    <button
                      onClick={() => handleDelete(year.id)}
                      className="p-1 text-red-600 hover:bg-red-100 rounded"
                    >
                      <Trash2 size={16} />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {years.length === 0 && (
        <div className="text-center py-8 text-gray-500">
          No academic years defined yet. Click "Add Year" to get started.
        </div>
      )}
    </div>
  );
}
