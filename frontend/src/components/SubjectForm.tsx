import { useState, useEffect } from 'react';
import { subjectsApi, subjectTypesApi, equipmentApi, teachersApi } from '../api/client';
import { Subject, DeliveryMode, BatchSchedulingMode, SubjectType, Equipment, Teacher } from '../types';
import { useDepartment } from '../context/DepartmentContext';
import { Plus, Edit, Trash2, Save, X, AlertTriangle } from 'lucide-react';
import { DataTable } from './DataTable';

const DELIVERY_MODE_INFO: Record<DeliveryMode, { label: string; hint: string }> = {
  IN_PERSON: { label: 'In-person (needs a teacher + room)', hint: 'Normal classroom teaching - this is what gets scheduled.' },
  MOOC_NPTEL: { label: 'NPTEL / other MOOC', hint: 'Taught and examined externally - never occupies a timetable slot.' },
  SELF_STUDY: { label: 'Self-study', hint: 'No teacher/room contention - counts for credit but is not scheduled.' },
  INDUSTRY: { label: 'Internship / industry', hint: 'Run outside the college - never occupies a timetable slot.' },
};

const slugify = (value: string) => value.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');

const DEFAULT_FORM = {
  id: '', name: '', code: '', type: 'theory',
  category: '', delivery_mode: 'IN_PERSON' as DeliveryMode,
  lecture_hours: 0, tutorial_hours: 0, practical_hours: 0,
  scheme_hours_per_week: 0,
  weekly_hours: null as number | null,
  weekly_hours_override: false,
  sessions_per_week: null as number | null,
  periods_per_session: 1,
  back_to_back: true,
  batch_scheduling_mode: 'independent' as BatchSchedulingMode,
  max_per_day: 1,
  requires_room_type: null as string | null,
  requires_equipment: [] as string[],
};

export function SubjectForm() {
  const { departmentId } = useDepartment();
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [subjectTypes, setSubjectTypes] = useState<SubjectType[]>([]);
  const [equipmentCatalog, setEquipmentCatalog] = useState<Equipment[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editingSubject, setEditingSubject] = useState<Subject | null>(null);
  const [formData, setFormData] = useState(DEFAULT_FORM);
  const [error, setError] = useState('');
  const [newTypeName, setNewTypeName] = useState('');
  const [allTeachers, setAllTeachers] = useState<Teacher[]>([]);
  const [qualifiedTeacherIds, setQualifiedTeacherIds] = useState<string[] | null>(null);

  useEffect(() => {
    fetchSubjects();
    fetchSubjectTypes();
    fetchEquipment();
    teachersApi.list().then((res) => setAllTeachers(res.data)).catch(() => setAllTeachers([]));
  }, []);

  // Which teachers can teach the subject currently being edited - the
  // reverse of a teacher's subject list, so "no one can teach this" is
  // visible here instead of only surfacing when generation fails (3.7).
  useEffect(() => {
    if (!editingSubject) { setQualifiedTeacherIds(null); return; }
    subjectsApi.getTeachers(editingSubject.id)
      .then((res) => setQualifiedTeacherIds(res.data))
      .catch(() => setQualifiedTeacherIds([]));
  }, [editingSubject]);

  const fetchSubjects = async () => {
    try {
      const response = await subjectsApi.list();
      setSubjects(response.data);
    } catch (err) {
      console.error('Failed to fetch subjects:', err);
    }
  };

  const fetchSubjectTypes = async () => {
    try {
      const response = await subjectTypesApi.list();
      setSubjectTypes(response.data);
    } catch (err) {
      console.error('Failed to fetch subject types:', err);
    }
  };

  const fetchEquipment = async () => {
    try {
      const response = await equipmentApi.list();
      setEquipmentCatalog(response.data);
    } catch (err) {
      console.error('Failed to fetch equipment:', err);
    }
  };

  const addSubjectType = async () => {
    if (!newTypeName.trim()) return;
    const id = slugify(newTypeName);
    try {
      const response = await subjectTypesApi.create({ id, name: newTypeName.trim(), default_block_size: 1, colour_hex: 'E5E7EB' });
      setSubjectTypes([...subjectTypes, response.data]);
      setFormData({ ...formData, type: id });
      setNewTypeName('');
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not add that subject type.');
    }
  };

  const addEquipment = async (name: string) => {
    const id = slugify(name);
    if (!id || equipmentCatalog.some((e) => e.id === id)) return id;
    try {
      const response = await equipmentApi.create({ id, name: name.trim() });
      setEquipmentCatalog([...equipmentCatalog, response.data]);
    } catch (err) {
      console.error('Failed to add equipment:', err);
    }
    return id;
  };

  const derivedWeeklyHours = formData.delivery_mode === 'IN_PERSON'
    ? formData.lecture_hours + formData.tutorial_hours + formData.practical_hours
    : 0;
  const effectiveWeeklyHours = formData.weekly_hours_override && formData.weekly_hours !== null
    ? formData.weekly_hours
    : derivedWeeklyHours;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    const payload = {
      ...formData,
      department_id: departmentId || null,
      weekly_hours: formData.weekly_hours_override ? formData.weekly_hours : null,
    };
    delete (payload as any).weekly_hours_override;
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
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not save the subject.');
    }
  };

  const handleEdit = (subject: Subject) => {
    setEditingSubject(subject);
    const derived = subject.delivery_mode === 'IN_PERSON'
      ? subject.lecture_hours + subject.tutorial_hours + subject.practical_hours
      : 0;
    setFormData({
      id: subject.id,
      name: subject.name,
      code: subject.code || '',
      type: subject.type,
      category: subject.category || '',
      delivery_mode: subject.delivery_mode || 'IN_PERSON',
      lecture_hours: subject.lecture_hours || 0,
      tutorial_hours: subject.tutorial_hours || 0,
      practical_hours: subject.practical_hours || 0,
      scheme_hours_per_week: subject.scheme_hours_per_week || 0,
      weekly_hours: subject.weekly_hours,
      weekly_hours_override: subject.weekly_hours !== derived,
      sessions_per_week: subject.sessions_per_week,
      periods_per_session: subject.periods_per_session,
      back_to_back: subject.back_to_back,
      batch_scheduling_mode: subject.batch_scheduling_mode,
      max_per_day: subject.max_per_day || 1,
      requires_room_type: subject.requires_room_type,
      requires_equipment: subject.requires_equipment || [],
    });
    setShowForm(true);
  };

  const handleDelete = async (id: string) => {
    if (window.confirm('Are you sure you want to delete this subject?')) {
      try {
        await subjectsApi.delete(id);
        fetchSubjects();
      } catch (err) {
        console.error('Failed to delete subject:', err);
      }
    }
  };

  const isSchedulable = formData.delivery_mode === 'IN_PERSON';
  const typeName = (id: string) => subjectTypes.find((t) => t.id === id)?.name || id;

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold">Subjects</h3>
        <button
          onClick={() => { setShowForm(true); setEditingSubject(null); setFormData(DEFAULT_FORM); setError(''); }}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          <Plus size={20} />
          Add Subject
        </button>
      </div>

      {error && <p className="mb-4 rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">{error}</p>}

      {showForm && (
        <div className="mb-6 p-4 border border-gray-200 rounded-lg bg-gray-50">
          {editingSubject && qualifiedTeacherIds !== null && (
            qualifiedTeacherIds.length === 0 ? (
              <div className="mb-4 flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                <AlertTriangle size={16} /> No teacher is qualified to teach this subject yet - it can't be scheduled until one is.
              </div>
            ) : (
              <p className="mb-4 text-sm text-gray-600">
                Can be taught by: {qualifiedTeacherIds.map((id) => allTeachers.find((t) => t.id === id)?.name || id).join(', ')}
              </p>
            )
          )}
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
                <label className="block text-sm font-medium text-gray-700 mb-1">Printed code (for exports)</label>
                <input
                  type="text" value={formData.code} onChange={(e) => setFormData({ ...formData, code: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder={`Defaults to "${formData.id.toUpperCase() || 'SUBJECT ID'}"`}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Type</label>
                <select
                  value={formData.type} onChange={(e) => setFormData({ ...formData, type: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  {subjectTypes.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select>
                <div className="flex gap-2 mt-1">
                  <input
                    type="text" value={newTypeName} onChange={(e) => setNewTypeName(e.target.value)}
                    placeholder="Add a new type (e.g. Seminar)"
                    className="flex-1 px-2 py-1 text-sm border border-gray-300 rounded"
                  />
                  <button type="button" onClick={addSubjectType} className="px-2 py-1 text-sm text-blue-700 bg-blue-50 hover:bg-blue-100 rounded">Add</button>
                </div>
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

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Hours per week, as printed in the scheme (L-T-P)</label>
              <div className="grid grid-cols-3 gap-3">
                <label className="text-xs text-gray-600">Lecture (L)
                  <input type="number" min="0" value={formData.lecture_hours}
                    onChange={(e) => setFormData({ ...formData, lecture_hours: parseInt(e.target.value) || 0 })}
                    className="mt-1 w-full px-3 py-2 border border-gray-300 rounded-lg" />
                </label>
                <label className="text-xs text-gray-600">Tutorial (T)
                  <input type="number" min="0" value={formData.tutorial_hours}
                    onChange={(e) => setFormData({ ...formData, tutorial_hours: parseInt(e.target.value) || 0 })}
                    className="mt-1 w-full px-3 py-2 border border-gray-300 rounded-lg" />
                </label>
                <label className="text-xs text-gray-600">Practical (P)
                  <input type="number" min="0" value={formData.practical_hours}
                    onChange={(e) => setFormData({ ...formData, practical_hours: parseInt(e.target.value) || 0 })}
                    className="mt-1 w-full px-3 py-2 border border-gray-300 rounded-lg" />
                </label>
              </div>
              <p className="text-xs text-gray-500 mt-1">
                A curriculum row with both lecture and tutorial hours should be entered as two separate
                subjects (one theory, one tutorial) - put each row's own hours here.
              </p>
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
                {formData.weekly_hours_override ? (
                  <input
                    type="number" min="0" value={formData.weekly_hours ?? 0} disabled={!isSchedulable}
                    onChange={(e) => setFormData({ ...formData, weekly_hours: parseInt(e.target.value) || 0 })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg disabled:bg-gray-100"
                  />
                ) : (
                  <input type="number" value={effectiveWeeklyHours} disabled className="w-full px-3 py-2 border border-gray-300 rounded-lg bg-gray-100" />
                )}
                <button
                  type="button"
                  onClick={() => setFormData({ ...formData, weekly_hours_override: !formData.weekly_hours_override, weekly_hours: formData.weekly_hours ?? derivedWeeklyHours })}
                  className="text-xs text-blue-600 hover:underline mt-1"
                >
                  {formData.weekly_hours_override ? 'Use derived L+T+P value instead' : 'Override this value'}
                </button>
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

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Sessions per week</label>
                <input
                  type="number" min="0" value={formData.sessions_per_week ?? ''}
                  placeholder="auto"
                  onChange={(e) => setFormData({ ...formData, sessions_per_week: e.target.value === '' ? null : parseInt(e.target.value) })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
                <p className="text-xs text-gray-500 mt-1">How many times it meets. Leave blank to derive from contact hours.</p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Periods per session</label>
                <input
                  type="number" min="1" value={formData.periods_per_session}
                  onChange={(e) => setFormData({ ...formData, periods_per_session: parseInt(e.target.value) || 1 })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
                <p className="text-xs text-gray-500 mt-1">1 for theory, 2-3 for a lab.</p>
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
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="flex items-center gap-2">
                <input
                  type="checkbox" id="back_to_back" checked={formData.back_to_back}
                  onChange={(e) => setFormData({ ...formData, back_to_back: e.target.checked })}
                  className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                />
                <label htmlFor="back_to_back" className="text-sm font-medium text-gray-700">
                  Periods must be back-to-back (e.g. a 2-hour lab block)
                </label>
              </div>
            </div>

            <div>
              <label htmlFor="batch_scheduling_mode" className="block text-sm font-medium text-gray-700 mb-1">
                Lab batches scheduling
              </label>
              <select
                id="batch_scheduling_mode" value={formData.batch_scheduling_mode}
                onChange={(e) => setFormData({ ...formData, batch_scheduling_mode: e.target.value as typeof formData.batch_scheduling_mode })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              >
                <option value="independent">Independent - no rule between batches (only a soft nudge)</option>
                <option value="parallel">Parallel - same time slot, separate rooms (and usually teachers)</option>
                <option value="sequential">Sequential - never at the same time</option>
                <option value="merged">Merged - same time, same room, same teacher (one combined class)</option>
              </select>
              <p className="text-xs text-gray-500 mt-1">
                {formData.batch_scheduling_mode === 'independent' && 'The solver decides freely; the "prefer lab batches in parallel" constraint weight (if set) still nudges them toward the same slot.'}
                {formData.batch_scheduling_mode === 'parallel' && 'Every batch’s session is forced into the same start slot, each in its own room. Needs one suitable room per batch, free at the same hour.'}
                {formData.batch_scheduling_mode === 'sequential' && 'Batches can never overlap in time - useful when they must share one teacher or room that can only handle one batch at a time.'}
                {formData.batch_scheduling_mode === 'merged' && 'All batches are taught together as one class: same slot, same room, same teacher. Needs one room big enough to seat every batch combined - check the lab batches preflight before generating.'}
              </p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Required Equipment</label>
              <div className="flex flex-wrap gap-2 mb-2">
                {equipmentCatalog.map((eq) => {
                  const selected = formData.requires_equipment.includes(eq.id);
                  return (
                    <button
                      key={eq.id} type="button"
                      onClick={() => setFormData({
                        ...formData,
                        requires_equipment: selected
                          ? formData.requires_equipment.filter((id) => id !== eq.id)
                          : [...formData.requires_equipment, eq.id],
                      })}
                      className={`px-2 py-1 text-xs rounded-full border ${selected ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-700 border-gray-300'}`}
                    >
                      {eq.name}
                    </button>
                  );
                })}
              </div>
              <div className="flex gap-2">
                <input
                  type="text" id="new-equipment" placeholder="Add new equipment (e.g. Projector)"
                  className="flex-1 px-2 py-1 text-sm border border-gray-300 rounded"
                  onKeyDown={async (e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      const input = e.currentTarget;
                      const id = await addEquipment(input.value);
                      if (id) setFormData((prev) => ({ ...prev, requires_equipment: [...prev.requires_equipment, id] }));
                      input.value = '';
                    }
                  }}
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

      <DataTable
        storageKey="subjects"
        rows={subjects}
        getRowId={(s) => s.id}
        emptyMessage='No subjects defined yet. Click "Add Subject" to get started.'
        searchPlaceholder="Search subjects"
        columns={[
          { key: 'id', header: 'ID', render: (s) => s.id },
          { key: 'name', header: 'Name', render: (s) => s.name },
          { key: 'code', header: 'Printed code', render: (s) => s.code || '-', defaultVisible: false },
          { key: 'type', header: 'Type', render: (s) => typeName(s.type) },
          {
            key: 'delivery', header: 'Delivery',
            render: (s) => s.delivery_mode === 'IN_PERSON'
              ? <span className="text-gray-700">Scheduled</span>
              : <span className="text-purple-600">{DELIVERY_MODE_INFO[s.delivery_mode]?.label || s.delivery_mode}</span>,
            searchValue: (s) => DELIVERY_MODE_INFO[s.delivery_mode]?.label || s.delivery_mode,
          },
          { key: 'hours', header: 'Hours/Week', render: (s) => (s.delivery_mode === 'IN_PERSON' ? String(s.weekly_hours) : '-') },
          { key: 'category', header: 'Category', render: (s) => s.category || '-', defaultVisible: false },
          { key: 'room_type', header: 'Room type', render: (s) => s.requires_room_type || 'Any', defaultVisible: false },
        ]}
        actions={(subject) => (
          <>
            <button onClick={() => handleEdit(subject)} className="p-1 text-blue-600 hover:bg-blue-100 rounded"><Edit size={16} /></button>
            <button onClick={() => handleDelete(subject.id)} className="p-1 text-red-600 hover:bg-red-100 rounded"><Trash2 size={16} /></button>
          </>
        )}
      />
    </div>
  );
}
