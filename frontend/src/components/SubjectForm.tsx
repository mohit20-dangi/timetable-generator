import { useState, useEffect } from 'react';
import { subjectsApi, sectionsApi, constraintsApi } from '../api/client';
import { Subject, Section, DeliveryMode } from '../types';
import { useDepartment } from '../context/DepartmentContext';
import { Plus, Edit, Trash2, Save, X, Link } from 'lucide-react';

const DELIVERY_MODE_INFO: Record<DeliveryMode, { label: string; hint: string }> = {
  IN_PERSON: { label: 'In-person (needs a teacher + room)', hint: 'Normal classroom teaching - this is what gets scheduled.' },
  MOOC_NPTEL: { label: 'NPTEL / other MOOC', hint: 'Taught and examined externally - never occupies a timetable slot.' },
  SELF_STUDY: { label: 'Self-study', hint: 'No teacher/room contention - counts for credit but is not scheduled.' },
  INDUSTRY: { label: 'Internship / industry', hint: 'Run outside the college - never occupies a timetable slot.' },
};

const DEFAULT_FORM = {
  id: '', name: '', type: 'theory' as 'theory' | 'lab' | 'tutorial',
  category: '', delivery_mode: 'IN_PERSON' as DeliveryMode,
  scheme_hours_per_week: 0, weekly_hours: 0,
  needs_continuous_block: false, block_size: 1, max_per_day: 1,
  requires_room_type: null as string | null,
  requires_equipment: [] as string[],
};

export function SubjectForm() {
  const { departmentId } = useDepartment();
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [sections, setSections] = useState<Section[]>([]);
  const [sectionSubjects, setSectionSubjects] = useState<Record<string, string[]>>({});
  const [showForm, setShowForm] = useState(false);
  const [editingSubject, setEditingSubject] = useState<Subject | null>(null);
  const [formData, setFormData] = useState(DEFAULT_FORM);

  useEffect(() => {
    fetchSubjects();
    fetchSections();
  }, []);

  const fetchSubjects = async () => {
    try {
      const response = await subjectsApi.list();
      setSubjects(response.data);
    } catch (error) {
      console.error('Failed to fetch subjects:', error);
    }
  };

  const fetchSections = async () => {
    try {
      const response = await sectionsApi.list();
      setSections(response.data);
      const subjMap: Record<string, string[]> = {};
      for (const section of response.data) {
        const ssResponse = await constraintsApi.getSectionSubjects(section.id);
        subjMap[section.id] = ssResponse.data.map((ss: any) => ss.subject_id);
      }
      setSectionSubjects(subjMap);
    } catch (error) {
      console.error('Failed to fetch sections:', error);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const payload = { ...formData, department_id: departmentId || null };
    try {
      if (editingSubject) {
        await subjectsApi.update(editingSubject.id, payload);
      } else {
        await subjectsApi.create(payload);
      }
      setShowForm(false);
      setEditingSubject(null);
      setFormData(DEFAULT_FORM);
      fetchSubjects();
    } catch (error) {
      console.error('Failed to save subject:', error);
    }
  };

  const handleEdit = (subject: Subject) => {
    setEditingSubject(subject);
    setFormData({
      id: subject.id,
      name: subject.name,
      type: subject.type as 'theory' | 'lab' | 'tutorial',
      category: subject.category || '',
      delivery_mode: subject.delivery_mode || 'IN_PERSON',
      scheme_hours_per_week: subject.scheme_hours_per_week || 0,
      weekly_hours: subject.weekly_hours,
      needs_continuous_block: subject.needs_continuous_block,
      block_size: subject.block_size,
      max_per_day: subject.max_per_day || 1,
      requires_room_type: subject.requires_room_type,
      requires_equipment: subject.requires_equipment || []
    });
    setShowForm(true);
  };

  const handleDelete = async (id: string) => {
    if (window.confirm('Are you sure you want to delete this subject?')) {
      try {
        await subjectsApi.delete(id);
        fetchSubjects();
      } catch (error) {
        console.error('Failed to delete subject:', error);
      }
    }
  };

  const toggleSectionSubject = async (sectionId: string, subjectId: string) => {
    try {
      const current = sectionSubjects[sectionId] || [];
      if (current.includes(subjectId)) {
        await constraintsApi.removeSectionSubject(sectionId, subjectId);
        setSectionSubjects({ ...sectionSubjects, [sectionId]: current.filter(id => id !== subjectId) });
      } else {
        await constraintsApi.addSectionSubject({ section_id: sectionId, subject_id: subjectId });
        setSectionSubjects({ ...sectionSubjects, [sectionId]: [...current, subjectId] });
      }
    } catch (error) {
      console.error('Failed to toggle section-subject:', error);
    }
  };

  const isSchedulable = formData.delivery_mode === 'IN_PERSON';

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold">Subjects</h3>
        <button
          onClick={() => { setShowForm(true); setEditingSubject(null); setFormData(DEFAULT_FORM); }}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          <Plus size={20} />
          Add Subject
        </button>
      </div>

      {showForm && (
        <div className="mb-6 p-4 border border-gray-200 rounded-lg bg-gray-50">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Subject ID</label>
                <input
                  type="text" value={formData.id} onChange={(e) => setFormData({ ...formData, id: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="e.g., cs101" required disabled={!!editingSubject}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Subject Name</label>
                <input
                  type="text" value={formData.name} onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="e.g., Data Structures" required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Type</label>
                <select
                  value={formData.type} onChange={(e) => setFormData({ ...formData, type: e.target.value as any })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  <option value="theory">Theory (lecture)</option>
                  <option value="lab">Lab / Practical</option>
                  <option value="tutorial">Tutorial</option>
                </select>
                <p className="text-xs text-gray-500 mt-1">
                  A curriculum row with both lecture and tutorial hours (e.g. L=3, T=1) should be
                  entered as two separate subjects, one theory and one tutorial.
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Scheme category (optional)</label>
                <input
                  type="text" value={formData.category} onChange={(e) => setFormData({ ...formData, category: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="e.g., PCC, MOEC, MC, INT"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">How is this delivered?</label>
              <select
                value={formData.delivery_mode}
                onChange={(e) => setFormData({ ...formData, delivery_mode: e.target.value as DeliveryMode })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              >
                {(Object.keys(DELIVERY_MODE_INFO) as DeliveryMode[]).map((mode) => (
                  <option key={mode} value={mode}>{DELIVERY_MODE_INFO[mode].label}</option>
                ))}
              </select>
              <p className="text-xs text-gray-500 mt-1">{DELIVERY_MODE_INFO[formData.delivery_mode].hint}</p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Scheme hours/week</label>
                <input
                  type="number" min="0" value={formData.scheme_hours_per_week}
                  onChange={(e) => setFormData({ ...formData, scheme_hours_per_week: parseInt(e.target.value) || 0 })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
                <p className="text-xs text-gray-500 mt-1">For credits/transcripts - not used for scheduling.</p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {isSchedulable ? 'Contact hours/week (scheduled)' : 'Contact hours/week (N/A)'}
                </label>
                <input
                  type="number" min="0" value={formData.weekly_hours} disabled={!isSchedulable}
                  onChange={(e) => setFormData({ ...formData, weekly_hours: parseInt(e.target.value) || 0 })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-100"
                />
                <p className="text-xs text-gray-500 mt-1">
                  {isSchedulable ? 'This many hours actually need a teacher + room this week.' : 'Not scheduled - leave at 0.'}
                </p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Max times per day</label>
                <input
                  type="number" min="1" value={formData.max_per_day}
                  onChange={(e) => setFormData({ ...formData, max_per_day: parseInt(e.target.value) || 1 })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="flex items-center gap-2">
                <input
                  type="checkbox" id="needs_continuous_block" checked={formData.needs_continuous_block}
                  onChange={(e) => setFormData({ ...formData, needs_continuous_block: e.target.checked })}
                  className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                />
                <label htmlFor="needs_continuous_block" className="text-sm font-medium text-gray-700">Needs a continuous block (e.g. a 2-hour lab)</label>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Block size (periods)</label>
                <input
                  type="number" min="1" value={formData.block_size}
                  onChange={(e) => setFormData({ ...formData, block_size: parseInt(e.target.value) || 1 })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Required Room Type</label>
                <select
                  value={formData.requires_room_type || ''}
                  onChange={(e) => setFormData({ ...formData, requires_room_type: e.target.value || null })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  <option value="">Any</option>
                  <option value="lecture">Lecture Hall</option>
                  <option value="lab">Lab</option>
                  <option value="seminar">Seminar Hall</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Required Equipment (comma-separated)</label>
                <input
                  type="text" value={formData.requires_equipment.join(', ')}
                  onChange={(e) => setFormData({ ...formData, requires_equipment: e.target.value.split(',').map(s => s.trim()).filter(Boolean) })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="e.g., computers, projector"
                />
              </div>
            </div>

            <div className="flex gap-2">
              <button type="submit" className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors">
                <Save size={20} />
                {editingSubject ? 'Update' : 'Save'}
              </button>
              <button
                type="button" onClick={() => { setShowForm(false); setEditingSubject(null); }}
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
              <th className="text-left px-4 py-2 font-medium text-gray-700">Type</th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">Delivery</th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">Hours/Week</th>
              <th className="text-right px-4 py-2 font-medium text-gray-700">Actions</th>
            </tr>
          </thead>
          <tbody>
            {subjects.map((subject) => (
              <tr key={subject.id} className="border-b border-gray-200">
                <td className="px-4 py-2">{subject.id}</td>
                <td className="px-4 py-2">{subject.name}</td>
                <td className="px-4 py-2 capitalize">{subject.type}</td>
                <td className="px-4 py-2 text-sm">
                  {subject.delivery_mode === 'IN_PERSON'
                    ? <span className="text-gray-700">Scheduled</span>
                    : <span className="text-purple-600">{DELIVERY_MODE_INFO[subject.delivery_mode]?.label || subject.delivery_mode}</span>}
                </td>
                <td className="px-4 py-2">{subject.delivery_mode === 'IN_PERSON' ? subject.weekly_hours : '-'}</td>
                <td className="px-4 py-2 text-right">
                  <button onClick={() => handleEdit(subject)} className="p-1 text-blue-600 hover:bg-blue-100 rounded"><Edit size={16} /></button>
                  <button onClick={() => handleDelete(subject.id)} className="p-1 text-red-600 hover:bg-red-100 rounded"><Trash2 size={16} /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {subjects.length === 0 && (
        <div className="text-center py-8 text-gray-500">No subjects defined yet. Click "Add Subject" to get started.</div>
      )}

      {sections.length > 0 && subjects.length > 0 && (
        <div className="mt-8">
          <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <Link size={20} />
            Assign Subjects to Sections
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead>
                <tr className="bg-gray-100">
                  <th className="text-left px-4 py-2 font-medium text-gray-700">Section</th>
                  {subjects.map((subject) => (
                    <th key={subject.id} className="text-center px-2 py-2 font-medium text-gray-700">{subject.id}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sections.map((section) => (
                  <tr key={section.id} className="border-b border-gray-200">
                    <td className="px-4 py-2 font-medium">{section.name}</td>
                    {subjects.map((subject) => {
                      const assigned = sectionSubjects[section.id]?.includes(subject.id);
                      return (
                        <td key={subject.id} className="text-center px-2 py-2">
                          <button
                            onClick={() => toggleSectionSubject(section.id, subject.id)}
                            className={`w-6 h-6 rounded flex items-center justify-center transition-colors ${
                              assigned ? 'bg-blue-600 text-white hover:bg-blue-700' : 'bg-gray-200 text-gray-600 hover:bg-gray-300'
                            }`}
                          >
                            {assigned ? '✓' : '+'}
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
