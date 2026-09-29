import { useState, useEffect } from 'react';
import { yearsApi, sectionsApi } from '../api/client';
import { AcademicYear, Section, LabBatch } from '../types';
import { Plus, Edit, Trash2, Save, X, ChevronDown, ChevronRight, FlaskConical } from 'lucide-react';
import { BulkUpload } from './BulkUpload';

const emptyFormData = { id: '', year_id: '', name: '', strength: 60 };

export function SectionForm() {
  const [years, setYears] = useState<AcademicYear[]>([]);
  const [sections, setSections] = useState<Section[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editingSection, setEditingSection] = useState<Section | null>(null);
  const [formData, setFormData] = useState(emptyFormData);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

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
    setSaving(true);
    try {
      if (editingSection) {
        await sectionsApi.update(editingSection.id, formData);
      } else {
        await sectionsApi.create(formData);
      }
      setShowForm(false);
      setEditingSection(null);
      setFormData(emptyFormData);
      fetchSections();
    } catch (error) {
      console.error('Failed to save section:', error);
    } finally {
      setSaving(false);
    }
  };

  const handleEdit = (section: Section) => {
    setEditingSection(section);
    setFormData({
      id: section.id,
      year_id: section.year_id,
      name: section.name,
      strength: section.strength,
    });
    setShowForm(true);
  };

  const handleDelete = async (id: string) => {
    if (window.confirm('Are you sure you want to delete this section?')) {
      try {
        await sectionsApi.delete(id);
        if (expandedId === id) setExpandedId(null);
        fetchSections();
      } catch (error) {
        console.error('Failed to delete section:', error);
      }
    }
  };

  const getYearName = (yearId: string) => years.find((y) => y.id === yearId)?.name || yearId;

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
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-100 disabled:text-gray-400"
                placeholder="e.g., y1_sec1"
                disabled={!!editingSection}
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
                onChange={(e) => setFormData({ ...formData, strength: parseInt(e.target.value) || 0 })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
            <div className="md:col-span-2 flex gap-2">
              <button
                type="submit"
                disabled={saving}
                className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 transition-colors"
              >
                <Save size={20} />
                {saving ? 'Saving...' : editingSection ? 'Update' : 'Save'}
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

      <div className="overflow-x-auto border border-gray-200 rounded-lg">
        <table className="w-full border-collapse">
          <thead>
            <tr className="bg-gray-100">
              <th className="w-8 px-2 py-2"></th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">ID</th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">Name</th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">Year</th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">Strength</th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">Lab Batches</th>
              <th className="text-right px-4 py-2 font-medium text-gray-700">Actions</th>
            </tr>
          </thead>
          <tbody>
            {sections.map((section) => {
              const isExpanded = expandedId === section.id;
              return (
                <SectionRow
                  key={section.id}
                  section={section}
                  yearName={getYearName(section.year_id)}
                  isExpanded={isExpanded}
                  onToggleExpand={() => setExpandedId(isExpanded ? null : section.id)}
                  onEdit={() => handleEdit(section)}
                  onDelete={() => handleDelete(section.id)}
                  onChanged={fetchSections}
                />
              );
            })}
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

interface SectionRowProps {
  section: Section;
  yearName: string;
  isExpanded: boolean;
  onToggleExpand: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onChanged: () => void;
}

function SectionRow({ section, yearName, isExpanded, onToggleExpand, onEdit, onDelete, onChanged }: SectionRowProps) {
  return (
    <>
      <tr className="border-b border-gray-200 hover:bg-gray-50">
        <td className="px-2 py-2 text-center">
          <button onClick={onToggleExpand} className="text-gray-500 hover:text-gray-800">
            {isExpanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
          </button>
        </td>
        <td className="px-4 py-2">{section.id}</td>
        <td className="px-4 py-2">{section.name}</td>
        <td className="px-4 py-2">{yearName}</td>
        <td className="px-4 py-2">{section.strength}</td>
        <td className="px-4 py-2">{section.lab_batches.length}</td>
        <td className="px-4 py-2 text-right whitespace-nowrap">
          <button onClick={onEdit} className="p-1 text-blue-600 hover:bg-blue-100 rounded">
            <Edit size={16} />
          </button>
          <button onClick={onDelete} className="p-1 text-red-600 hover:bg-red-100 rounded">
            <Trash2 size={16} />
          </button>
        </td>
      </tr>
      {isExpanded && (
        <tr className="border-b border-gray-200 bg-gray-50">
          <td colSpan={7} className="px-4 py-4">
            <LabBatchManager section={section} onChanged={onChanged} />
          </td>
        </tr>
      )}
    </>
  );
}

function LabBatchManager({ section, onChanged }: { section: Section; onChanged: () => void }) {
  const [showAdd, setShowAdd] = useState(false);
  const [newBatch, setNewBatch] = useState({ id: '', batch_name: '', strength: 30 });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await sectionsApi.createLabBatch(section.id, newBatch);
      setNewBatch({ id: '', batch_name: '', strength: 30 });
      setShowAdd(false);
      onChanged();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to add batch');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (batch: LabBatch) => {
    if (!window.confirm(`Delete batch "${batch.batch_name}"?`)) return;
    try {
      await sectionsApi.deleteLabBatch(section.id, batch.id);
      onChanged();
    } catch (err) {
      console.error('Failed to delete batch:', err);
    }
  };

  return (
    <div>
      <h5 className="text-sm font-semibold text-gray-700 mb-2 flex items-center gap-2">
        <FlaskConical size={16} />
        Lab Batches for {section.name}
      </h5>
      <p className="text-xs text-gray-500 mb-3">
        Split this section into smaller groups for lab subjects (e.g. a {section.strength}-student section into
        3 batches of ~{Math.ceil(section.strength / 3)}). By default each batch is scheduled independently and can
        land on a different day - use the "Batches run simultaneously" option on a subject (in the Subjects page)
        only if that specific lab needs every batch in class at the exact same time.
      </p>

      {section.lab_batches.length > 0 ? (
        <div className="border border-gray-200 rounded-lg divide-y divide-gray-200 bg-white mb-3">
          {section.lab_batches.map((batch) => (
            <div key={batch.id} className="flex items-center gap-3 px-3 py-2 text-sm">
              <span className="flex-1">
                <span className="font-medium">{batch.batch_name}</span>
                <span className="text-xs text-gray-400 ml-2">{batch.id}</span>
              </span>
              <span className="text-gray-500">{batch.strength} students</span>
              <button onClick={() => handleDelete(batch)} className="p-1 text-red-600 hover:bg-red-100 rounded">
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-gray-500 mb-3">No batches defined yet - lab subjects run as the whole section.</p>
      )}

      {showAdd ? (
        <form onSubmit={handleAdd} className="flex flex-wrap items-end gap-2 p-3 border border-gray-200 rounded-lg bg-white">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Batch ID</label>
            <input
              type="text"
              value={newBatch.id}
              onChange={(e) => setNewBatch({ ...newBatch, id: e.target.value })}
              placeholder="e.g. b1"
              className="px-2 py-1.5 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              required
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Batch Name</label>
            <input
              type="text"
              value={newBatch.batch_name}
              onChange={(e) => setNewBatch({ ...newBatch, batch_name: e.target.value })}
              placeholder="e.g. Batch 1"
              className="px-2 py-1.5 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              required
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Strength</label>
            <input
              type="number"
              min="1"
              value={newBatch.strength}
              onChange={(e) => setNewBatch({ ...newBatch, strength: parseInt(e.target.value) || 0 })}
              className="w-24 px-2 py-1.5 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>
          <button
            type="submit"
            disabled={saving}
            className="flex items-center gap-1 px-3 py-1.5 text-sm bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50"
          >
            <Save size={14} />
            {saving ? 'Saving...' : 'Save'}
          </button>
          <button
            type="button"
            onClick={() => setShowAdd(false)}
            className="flex items-center gap-1 px-3 py-1.5 text-sm bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300"
          >
            <X size={14} />
            Cancel
          </button>
        </form>
      ) : (
        <button
          onClick={() => setShowAdd(true)}
          className="flex items-center gap-2 px-3 py-1.5 text-sm text-blue-600 bg-blue-50 hover:bg-blue-100 rounded-lg"
        >
          <Plus size={16} />
          Add Batch
        </button>
      )}
      {error && <p className="text-sm text-red-600 mt-2">{error}</p>}
    </div>
  );
}
