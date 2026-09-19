import { useState, useEffect } from 'react';
import { yearsApi } from '../api/client';
import { AcademicYear } from '../types';
import { Plus, Edit, Trash2, Save, X } from 'lucide-react';
import { BulkUpload } from './BulkUpload';

export function AcademicYearForm() {
  const [years, setYears] = useState<AcademicYear[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editingYear, setEditingYear] = useState<AcademicYear | null>(null);
  const [formData, setFormData] = useState({
    id: '',
    name: '',
    lunch_start: '',
    lunch_end: ''
  });

  useEffect(() => {
    fetchYears();
  }, []);

  const fetchYears = async () => {
    try {
      const response = await yearsApi.list();
      setYears(response.data);
    } catch (error) {
      console.error('Failed to fetch years:', error);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      if (editingYear) {
        // Update logic would go here
      } else {
        await yearsApi.create(formData);
      }
      setShowForm(false);
      setEditingYear(null);
      setFormData({ id: '', name: '', lunch_start: '', lunch_end: '' });
      fetchYears();
    } catch (error) {
      console.error('Failed to save year:', error);
    }
  };

  const handleEdit = (year: AcademicYear) => {
    setEditingYear(year);
    setFormData({
      id: year.id,
      name: year.name,
      lunch_start: year.lunch_start || '',
      lunch_end: year.lunch_end || ''
    });
    setShowForm(true);
  };

  const handleDelete = async (id: string) => {
    if (window.confirm('Are you sure you want to delete this academic year?')) {
      try {
        await yearsApi.delete(id);
        fetchYears();
      } catch (error) {
        console.error('Failed to delete year:', error);
      }
    }
  };

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold">Academic Years</h3>
        <div className="flex gap-2">
          <BulkUpload label="Academic Years" uploadPath="/years/bulk" templatePath="/years/bulk/template" onDone={fetchYears} />
          <button
            onClick={() => {
              setShowForm(true);
              setEditingYear(null);
              setFormData({ id: '', name: '', lunch_start: '', lunch_end: '' });
            }}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
          >
            <Plus size={20} />
            Add Year
          </button>
        </div>
      </div>

      {showForm && (
        <div className="mb-6 p-4 border border-gray-200 rounded-lg bg-gray-50">
          <form onSubmit={handleSubmit} className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Year ID</label>
              <input
                type="text"
                value={formData.id}
                onChange={(e) => setFormData({ ...formData, id: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                placeholder="e.g., y1"
                required
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
              <label className="block text-sm font-medium text-gray-700 mb-1">Lunch Start</label>
              <input
                type="time"
                value={formData.lunch_start}
                onChange={(e) => setFormData({ ...formData, lunch_start: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Lunch End</label>
              <input
                type="time"
                value={formData.lunch_end}
                onChange={(e) => setFormData({ ...formData, lunch_end: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
            <div className="flex items-end gap-2">
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
              <th className="text-left px-4 py-2 font-medium text-gray-700">Lunch Break</th>
              <th className="text-right px-4 py-2 font-medium text-gray-700">Actions</th>
            </tr>
          </thead>
          <tbody>
            {years.map((year) => (
              <tr key={year.id} className="border-b border-gray-200">
                <td className="px-4 py-2">{year.id}</td>
                <td className="px-4 py-2">{year.name}</td>
                <td className="px-4 py-2">
                  {year.lunch_start && year.lunch_end 
                    ? `${year.lunch_start} - ${year.lunch_end}` 
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
            ))}
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