import { useState, useEffect } from 'react';
import { yearsApi, sectionsApi } from '../api/client';
import { AcademicYear, Section } from '../types';
import { Plus, Edit, Trash2, Save, X } from 'lucide-react';
import { BulkUpload } from './BulkUpload';

export function SectionForm() {
  const [years, setYears] = useState<AcademicYear[]>([]);
  const [sections, setSections] = useState<Section[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editingSection, setEditingSection] = useState<Section | null>(null);
  const [formData, setFormData] = useState({
    id: '',
    year_id: '',
    name: '',
    strength: 60
  });

  useEffect(() => {
    fetchYears();
    fetchSections();
  }, []);

  const fetchYears = async () => {
    try {
      const response = await yearsApi.list();
      setYears(response.data);
    } catch (error) {
      console.error('Failed to fetch years:', error);
    }
  };

  const fetchSections = async () => {
    try {
      const response = await sectionsApi.list();
      setSections(response.data);
    } catch (error) {
      console.error('Failed to fetch sections:', error);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      if (editingSection) {
        // Update logic would go here
      } else {
        await sectionsApi.create(formData);
      }
      setShowForm(false);
      setEditingSection(null);
      setFormData({ id: '', year_id: '', name: '', strength: 60 });
      fetchSections();
    } catch (error) {
      console.error('Failed to save section:', error);
    }
  };

  const handleEdit = (section: Section) => {
    setEditingSection(section);
    setFormData({
      id: section.id,
      year_id: section.year_id,
      name: section.name,
      strength: section.strength
    });
    setShowForm(true);
  };

  const handleDelete = async (id: string) => {
    if (window.confirm('Are you sure you want to delete this section?')) {
      try {
        await sectionsApi.delete(id);
        fetchSections();
      } catch (error) {
        console.error('Failed to delete section:', error);
      }
    }
  };

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold">Sections</h3>
        <div className="flex gap-2">
          <BulkUpload label="Sections" uploadPath="/sections/bulk" templatePath="/sections/bulk/template" onDone={fetchSections} />
          <button
            onClick={() => {
              setShowForm(true);
              setEditingSection(null);
              setFormData({ id: '', year_id: years[0]?.id || '', name: '', strength: 60 });
            }}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
          >
            <Plus size={20} />
            Add Section
          </button>
        </div>
      </div>

      {showForm && (
        <div className="mb-6 p-4 border border-gray-200 rounded-lg bg-gray-50">
          <form onSubmit={handleSubmit} className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Section ID</label>
              <input
                type="text"
                value={formData.id}
                onChange={(e) => setFormData({ ...formData, id: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                placeholder="e.g., y1_sec1"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Academic Year</label>
              <select
                value={formData.year_id}
                onChange={(e) => setFormData({ ...formData, year_id: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                required
              >
                <option value="">Select Year</option>
                {years.map((year) => (
                  <option key={year.id} value={year.id}>{year.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Section Name</label>
              <input
                type="text"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                placeholder="e.g., Section A"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Strength</label>
              <input
                type="number"
                min="1"
                value={formData.strength}
                onChange={(e) => setFormData({ ...formData, strength: parseInt(e.target.value) })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
            <div className="md:col-span-2 flex gap-2">
              <button
                type="submit"
                className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors"
              >
                <Save size={20} />
                {editingSection ? 'Update' : 'Save'}
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowForm(false);
                  setEditingSection(null);
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
              <th className="text-left px-4 py-2 font-medium text-gray-700">Year</th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">Strength</th>
              <th className="text-right px-4 py-2 font-medium text-gray-700">Actions</th>
            </tr>
          </thead>
          <tbody>
            {sections.map((section) => (
              <tr key={section.id} className="border-b border-gray-200">
                <td className="px-4 py-2">{section.id}</td>
                <td className="px-4 py-2">{section.name}</td>
                <td className="px-4 py-2">{section.year_id}</td>
                <td className="px-4 py-2">{section.strength}</td>
                <td className="px-4 py-2 text-right">
                  <button
                    onClick={() => handleEdit(section)}
                    className="p-1 text-blue-600 hover:bg-blue-100 rounded"
                  >
                    <Edit size={16} />
                  </button>
                  <button
                    onClick={() => handleDelete(section.id)}
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

      {sections.length === 0 && (
        <div className="text-center py-8 text-gray-500">
          No sections defined yet. Click "Add Section" to get started.
        </div>
      )}
    </div>
  );
}