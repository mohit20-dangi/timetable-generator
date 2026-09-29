import { useState, useEffect, useMemo } from 'react';
import { subjectsApi, sectionsApi } from '../api/client';
import { Subject, Section, SectionSubjectLink } from '../types';
import { Plus, Edit, Trash2, Save, X, Search, ChevronDown, ChevronRight, Link2, ListChecks } from 'lucide-react';
import { BulkUpload } from './BulkUpload';

const emptyFormData = {
  id: '',
  name: '',
  type: 'theory' as 'theory' | 'lab' | 'tutorial',
  weekly_hours: 0,
  needs_continuous_block: false,
  block_size: 1,
  requires_room_type: null as string | null,
  requires_equipment: [] as string[],
};

export function SubjectForm() {
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [sections, setSections] = useState<Section[]>([]);
  const [search, setSearch] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [editingSubject, setEditingSubject] = useState<Subject | null>(null);
  const [formData, setFormData] = useState(emptyFormData);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

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
    } catch (error) {
      console.error('Failed to fetch sections:', error);
    }
  };

  const filteredSubjects = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return subjects;
    return subjects.filter(
      (s) => s.name.toLowerCase().includes(q) || s.id.toLowerCase().includes(q) || s.type.toLowerCase().includes(q)
    );
  }, [subjects, search]);

  const openAddForm = () => {
    setEditingSubject(null);
    setFormData(emptyFormData);
    setShowForm(true);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      if (editingSubject) {
        await subjectsApi.update(editingSubject.id, formData);
      } else {
        await subjectsApi.create(formData);
      }
      setShowForm(false);
      setEditingSubject(null);
      setFormData(emptyFormData);
      fetchSubjects();
    } catch (error) {
      console.error('Failed to save subject:', error);
    } finally {
      setSaving(false);
    }
  };

  const handleEdit = (subject: Subject) => {
    setEditingSubject(subject);
    setFormData({
      id: subject.id,
      name: subject.name,
      type: subject.type,
      weekly_hours: subject.weekly_hours,
      needs_continuous_block: subject.needs_continuous_block,
      block_size: subject.block_size,
      requires_room_type: subject.requires_room_type,
      requires_equipment: subject.requires_equipment || [],
    });
    setShowForm(true);
  };

  const handleDelete = async (id: string) => {
    if (window.confirm('Delete this subject? This also removes it from any sections, teachers, and prerequisite lists.')) {
      try {
        await subjectsApi.delete(id);
        if (expandedId === id) setExpandedId(null);
        fetchSubjects();
        fetchSections();
      } catch (error) {
        console.error('Failed to delete subject:', error);
      }
    }
  };

  const sectionsOffering = (subjectId: string) =>
    sections.filter((s) => s.subjects.some((l) => l.subject_id === subjectId)).length;

  return (
    <div>
      <div className="flex flex-wrap justify-between items-center gap-3 mb-4">
        <h3 className="text-lg font-semibold">Subjects</h3>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search size={16} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search subjects..."
              className="pl-8 pr-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>
          <BulkUpload label="Subjects" uploadPath="/subjects/bulk" templatePath="/subjects/bulk/template" onDone={fetchSubjects} />
          <button
            onClick={openAddForm}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
          >
            <Plus size={20} />
            Add Subject
          </button>
        </div>
      </div>

      {showForm && (
        <div className="mb-6 p-4 border border-gray-200 rounded-lg bg-gray-50">
          <div className="flex justify-between items-center mb-3">
            <h4 className="font-medium text-gray-800">{editingSubject ? `Edit ${editingSubject.name}` : 'New Subject'}</h4>
          </div>
          <form onSubmit={handleSubmit} className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Subject ID</label>
              <input
                type="text"
                value={formData.id}
                onChange={(e) => setFormData({ ...formData, id: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-100 disabled:text-gray-400"
                placeholder="e.g., cs101"
                disabled={!!editingSubject}
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Subject Name</label>
              <input
                type="text"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                placeholder="e.g., Data Structures"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Type</label>
              <select
                value={formData.type}
                onChange={(e) => setFormData({ ...formData, type: e.target.value as any })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              >
                <option value="theory">Theory</option>
                <option value="lab">Lab</option>
                <option value="tutorial">Tutorial</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Weekly Hours</label>
              <input
                type="number"
                min="0"
                value={formData.weekly_hours}
                onChange={(e) => setFormData({ ...formData, weekly_hours: parseInt(e.target.value) || 0 })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="needs_continuous_block"
                checked={formData.needs_continuous_block}
                onChange={(e) => setFormData({ ...formData, needs_continuous_block: e.target.checked })}
                className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
              />
              <label htmlFor="needs_continuous_block" className="text-sm font-medium text-gray-700">
                Needs Continuous Block
              </label>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Block Size</label>
              <input
                type="number"
                min="1"
                value={formData.block_size}
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
                type="text"
                value={formData.requires_equipment.join(', ')}
                onChange={(e) => setFormData({ ...formData, requires_equipment: e.target.value.split(',').map(s => s.trim()).filter(Boolean) })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                placeholder="e.g., computers, projector"
              />
            </div>
            <div className="md:col-span-2 flex gap-2">
              <button
                type="submit"
                disabled={saving}
                className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 transition-colors"
              >
                <Save size={20} />
                {saving ? 'Saving...' : editingSubject ? 'Update' : 'Save'}
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowForm(false);
                  setEditingSubject(null);
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
              <th className="text-left px-4 py-2 font-medium text-gray-700">Name</th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">Type</th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">Hours/Week</th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">Room Type</th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">Sections</th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">Prerequisites</th>
              <th className="text-right px-4 py-2 font-medium text-gray-700">Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredSubjects.map((subject) => {
              const isExpanded = expandedId === subject.id;
              return (
                <SubjectRow
                  key={subject.id}
                  subject={subject}
                  subjects={subjects}
                  sections={sections}
                  isExpanded={isExpanded}
                  sectionCount={sectionsOffering(subject.id)}
                  onToggleExpand={() => setExpandedId(isExpanded ? null : subject.id)}
                  onEdit={() => handleEdit(subject)}
                  onDelete={() => handleDelete(subject.id)}
                  onSectionsChanged={fetchSections}
                  onSubjectsChanged={fetchSubjects}
                />
              );
            })}
          </tbody>
        </table>
      </div>

      {filteredSubjects.length === 0 && (
        <div className="text-center py-8 text-gray-500">
          {subjects.length === 0
            ? 'No subjects defined yet. Click "Add Subject" to get started.'
            : 'No subjects match your search.'}
        </div>
      )}
    </div>
  );
}

interface SubjectRowProps {
  subject: Subject;
  subjects: Subject[];
  sections: Section[];
  isExpanded: boolean;
  sectionCount: number;
  onToggleExpand: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onSectionsChanged: () => void;
  onSubjectsChanged: () => void;
}

function SubjectRow({
  subject, subjects, sections, isExpanded, sectionCount,
  onToggleExpand, onEdit, onDelete, onSectionsChanged, onSubjectsChanged,
}: SubjectRowProps) {
  return (
    <>
      <tr className="border-b border-gray-200 hover:bg-gray-50">
        <td className="px-2 py-2 text-center">
          <button onClick={onToggleExpand} className="text-gray-500 hover:text-gray-800">
            {isExpanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
          </button>
        </td>
        <td className="px-4 py-2">
          <div className="font-medium">{subject.name}</div>
          <div className="text-xs text-gray-400">{subject.id}</div>
        </td>
        <td className="px-4 py-2 capitalize">{subject.type}</td>
        <td className="px-4 py-2">{subject.weekly_hours}</td>
        <td className="px-4 py-2">{subject.requires_room_type || 'Any'}</td>
        <td className="px-4 py-2">{sectionCount}</td>
        <td className="px-4 py-2">{subject.prerequisite_ids.length}</td>
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
          <td colSpan={8} className="px-4 py-4">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <SectionAssignment
                subject={subject}
                sections={sections}
                onChanged={onSectionsChanged}
              />
              <PrerequisitePicker
                subject={subject}
                subjects={subjects}
                onChanged={onSubjectsChanged}
              />
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function SectionAssignment({ subject, sections, onChanged }: { subject: Subject; sections: Section[]; onChanged: () => void }) {
  const [busySectionId, setBusySectionId] = useState<string | null>(null);

  const linkFor = (section: Section): SectionSubjectLink | undefined =>
    section.subjects.find((l) => l.subject_id === subject.id);

  const toggleAssigned = async (section: Section) => {
    setBusySectionId(section.id);
    try {
      const link = linkFor(section);
      if (link) {
        await sectionsApi.removeSubject(section.id, subject.id);
      } else {
        await sectionsApi.addSubject(section.id, {
          subject_id: subject.id, is_elective: false, elective_group_id: null, batches_simultaneous: false,
        });
      }
      onChanged();
    } catch (error) {
      console.error('Failed to update section assignment:', error);
    } finally {
      setBusySectionId(null);
    }
  };

  // addSubject replaces the whole link, so every call must carry the link's
  // full current state forward - omitting a field here would silently reset
  // it to its default instead of leaving it untouched.
  const updateLink = async (section: Section, patch: Partial<SectionSubjectLink>) => {
    const link = linkFor(section);
    if (!link) return;
    setBusySectionId(section.id);
    try {
      const merged = { ...link, ...patch };
      if (!merged.is_elective) merged.elective_group_id = null;
      await sectionsApi.addSubject(section.id, {
        subject_id: subject.id,
        is_elective: merged.is_elective,
        elective_group_id: merged.elective_group_id,
        batches_simultaneous: merged.batches_simultaneous,
      });
      onChanged();
    } catch (error) {
      console.error('Failed to update section-subject link:', error);
    } finally {
      setBusySectionId(null);
    }
  };

  return (
    <div>
      <h5 className="text-sm font-semibold text-gray-700 mb-2 flex items-center gap-2">
        <Link2 size={16} />
        Offered in Sections
      </h5>
      {sections.length === 0 ? (
        <p className="text-sm text-gray-500">No sections defined yet.</p>
      ) : (
        <div className="border border-gray-200 rounded-lg divide-y divide-gray-200 bg-white max-h-72 overflow-y-auto">
          {sections.map((section) => {
            const link = linkFor(section);
            const assigned = !!link;
            const busy = busySectionId === section.id;
            return (
              <div key={section.id} className="flex items-center gap-3 px-3 py-2">
                <input
                  type="checkbox"
                  checked={assigned}
                  disabled={busy}
                  onChange={() => toggleAssigned(section)}
                  className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500 disabled:opacity-50"
                />
                <span className="flex-1 text-sm" title={section.name}>{section.id}</span>
                {assigned && (
                  <>
                    <label className="flex items-center gap-1 text-xs text-gray-500">
                      <input
                        type="checkbox"
                        checked={link!.is_elective}
                        disabled={busy}
                        onChange={(e) => updateLink(section, { is_elective: e.target.checked })}
                        className="w-3.5 h-3.5 text-blue-600 border-gray-300 rounded focus:ring-blue-500 disabled:opacity-50"
                      />
                      Elective
                    </label>
                    <input
                      type="text"
                      value={link!.elective_group_id || ''}
                      disabled={!link!.is_elective || busy}
                      onChange={(e) => updateLink(section, { elective_group_id: e.target.value })}
                      placeholder="group name"
                      className="w-28 px-2 py-1 text-xs border border-gray-300 rounded disabled:bg-gray-100 disabled:text-gray-400 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    />
                    {subject.type === 'lab' && section.lab_batches.length > 0 && (
                      <label className="flex items-center gap-1 text-xs text-gray-500" title="By default each batch picks its own day/slot independently">
                        <input
                          type="checkbox"
                          checked={link!.batches_simultaneous}
                          disabled={busy}
                          onChange={(e) => updateLink(section, { batches_simultaneous: e.target.checked })}
                          className="w-3.5 h-3.5 text-blue-600 border-gray-300 rounded focus:ring-blue-500 disabled:opacity-50"
                        />
                        Batches simultaneous
                      </label>
                    )}
                  </>
                )}
              </div>
            );
          })}
        </div>
      )}
      <p className="text-xs text-gray-500 mt-2">
        Electives that share the same group name are scheduled at the same slot, so a student can pick either without a clash.
        {subject.type === 'lab' && ' For a lab split into batches (manage those on the Sections page), each batch schedules independently by default - check "Batches simultaneous" only if every batch must be in class at the same time.'}
      </p>
    </div>
  );
}

function PrerequisitePicker({ subject, subjects, onChanged }: { subject: Subject; subjects: Subject[]; onChanged: () => void }) {
  const [busyId, setBusyId] = useState<string | null>(null);
  const candidates = subjects.filter((s) => s.id !== subject.id);

  const toggle = async (requiresId: string) => {
    setBusyId(requiresId);
    try {
      if (subject.prerequisite_ids.includes(requiresId)) {
        await subjectsApi.removePrerequisite(subject.id, requiresId);
      } else {
        await subjectsApi.addPrerequisite(subject.id, requiresId);
      }
      onChanged();
    } catch (error) {
      console.error('Failed to update prerequisites:', error);
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div>
      <h5 className="text-sm font-semibold text-gray-700 mb-2 flex items-center gap-2">
        <ListChecks size={16} />
        Prerequisites
      </h5>
      {candidates.length === 0 ? (
        <p className="text-sm text-gray-500">No other subjects to depend on yet.</p>
      ) : (
        <div className="border border-gray-200 rounded-lg divide-y divide-gray-200 bg-white max-h-72 overflow-y-auto">
          {candidates.map((candidate) => {
            const checked = subject.prerequisite_ids.includes(candidate.id);
            const busy = busyId === candidate.id;
            return (
              <label key={candidate.id} className="flex items-center gap-3 px-3 py-2 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={busy}
                  onChange={() => toggle(candidate.id)}
                  className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500 disabled:opacity-50"
                />
                {candidate.name}
              </label>
            );
          })}
        </div>
      )}
      <p className="text-xs text-gray-500 mt-2">
        Must be scheduled before {subject.name} in the week.
      </p>
    </div>
  );
}
