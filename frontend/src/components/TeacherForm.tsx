import { useState, useEffect } from 'react';
import { teachersApi, subjectsApi, departmentsApi, constraintsApi } from '../api/client';
import { Teacher, Subject, Department } from '../types';
import { useDepartment } from '../context/DepartmentContext';
import { Plus, Edit, Trash2, Save, X, AlertTriangle } from 'lucide-react';
import { DataTable } from './DataTable';
import { HelpPopover } from './HelpPopover';
import { DEFAULT_SLOTS, ScheduleSlot } from '../utils/schedule';
import { validateWindows, validatePreferredWithinAvailability, validateWorkloadCaps } from '../utils/validation';

export function TeacherForm() {
  const { departmentId } = useDepartment();
  const [teachers, setTeachers] = useState<Teacher[]>([]);
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [scheduleSlots, setScheduleSlots] = useState<ScheduleSlot[]>(DEFAULT_SLOTS);
  const [showForm, setShowForm] = useState(false);
  const [editingTeacher, setEditingTeacher] = useState<Teacher | null>(null);
  const [formData, setFormData] = useState({
    id: '',
    name: '',
    initials: '',
    department_id: '',
    max_continuous_classes: 3,
    max_daily_classes: 5,
    availability: [] as Array<{ day: string; start: string; end: string }>,
    preferred_slots: [] as Array<{ day: string; slots: Array<{ start: string; end: string }> }>,
    is_guest_from_other_dept: false,
    subjects: [] as string[]
  });

  const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const [error, setError] = useState('');

  const availabilityIssues = validateWindows(formData.availability, scheduleSlots);
  const preferredFlat = formData.preferred_slots.flatMap((d) => d.slots.map((s) => ({ day: d.day, start: s.start, end: s.end })));
  const preferredIssues = [
    ...validateWindows(preferredFlat, scheduleSlots),
    ...validatePreferredWithinAvailability(preferredFlat, formData.availability, formData.name || 'This teacher'),
  ];
  const workloadIssues = validateWorkloadCaps(
    { maxDailyClasses: formData.max_daily_classes, maxContinuousClasses: formData.max_continuous_classes },
    scheduleSlots,
  );
  const blockingIssues = [...availabilityIssues, ...preferredIssues].filter((i) => i.severity === 'error');

  useEffect(() => {
    fetchTeachers();
    fetchSubjects();
    departmentsApi.list().then((res) => setDepartments(res.data)).catch(() => setDepartments([]));
    constraintsApi.listTimeSlots().then((res) => setScheduleSlots(res.data.length ? res.data : DEFAULT_SLOTS)).catch(() => {});
  }, []);

  const fetchTeachers = async () => {
    try {
      const response = await teachersApi.list();
      setTeachers(response.data);
    } catch (error) {
      console.error('Failed to fetch teachers:', error);
    }
  };

  const fetchSubjects = async () => {
    try {
      const response = await subjectsApi.list();
      setSubjects(response.data);
    } catch (error) {
      console.error('Failed to fetch subjects:', error);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (blockingIssues.length > 0) {
      setError(blockingIssues[0].message);
      return;
    }
    try {
      if (editingTeacher) {
        await teachersApi.update(editingTeacher.id, formData);
      } else {
        await teachersApi.create(formData);
      }
      setShowForm(false);
      setEditingTeacher(null);
      resetForm();
      fetchTeachers();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not save this teacher.');
    }
  };

  const resetForm = () => {
    setFormData({
      id: '', name: '', initials: '', department_id: departmentId || '',
      max_continuous_classes: 3, max_daily_classes: 5,
      availability: [], preferred_slots: [],
      is_guest_from_other_dept: false, subjects: []
    });
  };

  const handleEdit = async (teacher: Teacher) => {
    setEditingTeacher(teacher);
    setFormData({
      id: teacher.id,
      name: teacher.name,
      initials: teacher.initials || '',
      department_id: teacher.department_id || '',
      max_continuous_classes: teacher.max_continuous_classes,
      max_daily_classes: teacher.max_daily_classes,
      availability: teacher.availability || [],
      preferred_slots: teacher.preferred_slots || [],
      is_guest_from_other_dept: teacher.is_guest_from_other_dept,
      subjects: []
    });
    setShowForm(true);
    try {
      const response = await teachersApi.getSubjects(teacher.id);
      setFormData((current) => ({ ...current, subjects: response.data }));
    } catch (error) {
      console.error('Failed to load this teacher\'s subjects:', error);
    }
  };

  const handleDelete = async (id: string) => {
    if (window.confirm('Are you sure you want to delete this teacher?')) {
      try {
        await teachersApi.delete(id);
        fetchTeachers();
      } catch (error) {
        console.error('Failed to delete teacher:', error);
      }
    }
  };

  const addAvailabilitySlot = () => {
    setFormData({
      ...formData,
      availability: [...formData.availability, { day: 'Mon', start: '09:00', end: '16:00' }]
    });
  };

  const updateAvailabilitySlot = (index: number, field: string, value: string) => {
    const newAvailability = [...formData.availability];
    newAvailability[index] = { ...newAvailability[index], [field]: value };
    setFormData({ ...formData, availability: newAvailability });
  };

  const removeAvailabilitySlot = (index: number) => {
    const newAvailability = [...formData.availability];
    newAvailability.splice(index, 1);
    setFormData({ ...formData, availability: newAvailability });
  };

  const toggleSubject = (subjectId: string) => {
    if (formData.subjects.includes(subjectId)) {
      setFormData({
        ...formData,
        subjects: formData.subjects.filter(id => id !== subjectId)
      });
    } else {
      setFormData({
        ...formData,
        subjects: [...formData.subjects, subjectId]
      });
    }
  };

  const selectAllSubjects = () => setFormData({ ...formData, subjects: subjects.map((s) => s.id) });
  const clearAllSubjects = () => setFormData({ ...formData, subjects: [] });

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold">Teachers</h3>
        <button
          onClick={() => {
            setShowForm(true);
            setEditingTeacher(null);
            resetForm();
          }}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          <Plus size={20} />
          Add Teacher
        </button>
      </div>

      {error && <p className="mb-4 rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">{error}</p>}

      {showForm && (
        <div className="mb-6 p-4 border border-gray-200 rounded-lg bg-gray-50">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Teacher ID</label>
                <input
                  type="text"
                  value={formData.id}
                  onChange={(e) => setFormData({ ...formData, id: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="e.g., t1"
                  required
                  disabled={!!editingTeacher}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
                <input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="e.g., Prof. Sharma"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Printed initials (for exports)</label>
                <input
                  type="text"
                  value={formData.initials}
                  onChange={(e) => setFormData({ ...formData, initials: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="Derived from name if left blank"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Department</label>
                <select
                  value={formData.department_id}
                  onChange={(e) => setFormData({ ...formData, department_id: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  <option value="">Select department</option>
                  {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                </select>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Max Continuous Classes</label>
                <input
                  type="number"
                  min="1"
                  value={formData.max_continuous_classes}
                  onChange={(e) => setFormData({ ...formData, max_continuous_classes: Number(e.target.value) || 0 })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
                <div className="mt-1"><HelpPopover>The longest run of back-to-back periods this teacher will be scheduled for on one day, before a gap is required.</HelpPopover></div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Max Daily Classes</label>
                <input
                  type="number"
                  min="1"
                  value={formData.max_daily_classes}
                  onChange={(e) => setFormData({ ...formData, max_daily_classes: Number(e.target.value) || 0 })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
                <div className="mt-1"><HelpPopover>The most periods this teacher will be scheduled for in a single day, regardless of subject.</HelpPopover></div>
              </div>
              <div className="flex items-end">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={formData.is_guest_from_other_dept}
                    onChange={(e) => setFormData({ ...formData, is_guest_from_other_dept: e.target.checked })}
                    className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                  />
                  <span className="text-sm font-medium text-gray-700">Guest from other dept</span>
                </label>
              </div>
            </div>
            {workloadIssues.length > 0 && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 space-y-1">
                {workloadIssues.map((issue, i) => <p key={i} className="flex items-center gap-2"><AlertTriangle size={14} /> {issue.message}</p>)}
              </div>
            )}

            {/* Availability */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="block text-sm font-medium text-gray-700">When can they teach?</label>
                <button
                  type="button"
                  onClick={addAvailabilitySlot}
                  className="text-sm text-blue-600 hover:text-blue-800"
                >
                  + Add Slot
                </button>
              </div>
              {formData.availability.map((slot, index) => (
                <div key={index} className="flex items-center gap-2 mb-2">
                  <select
                    value={slot.day}
                    onChange={(e) => updateAvailabilitySlot(index, 'day', e.target.value)}
                    className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  >
                    {days.map((day) => (
                      <option key={day} value={day}>{day}</option>
                    ))}
                  </select>
                  <input
                    type="time"
                    value={slot.start}
                    onChange={(e) => updateAvailabilitySlot(index, 'start', e.target.value)}
                    className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                  <span className="text-gray-500">to</span>
                  <input
                    type="time"
                    value={slot.end}
                    onChange={(e) => updateAvailabilitySlot(index, 'end', e.target.value)}
                    className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  />
                  <button
                    type="button"
                    onClick={() => removeAvailabilitySlot(index)}
                    className="p-1 text-red-600 hover:bg-red-100 rounded"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              ))}
              {availabilityIssues.map((issue, i) => (
                <p key={i} className={`text-xs mt-1 flex items-center gap-1 ${issue.severity === 'error' ? 'text-red-600' : 'text-amber-600'}`}>
                  <AlertTriangle size={12} /> {issue.message}
                </p>
              ))}
            </div>

            {/* Preferred Time Slots (Multiple Intervals) */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">When do they prefer to teach?</label>
              <p className="text-sm text-gray-500 mb-2">
                Define time ranges when the teacher prefers to teach (can have multiple intervals per day)
              </p>
              <div className="space-y-3">
                {formData.preferred_slots.map((daySlot, dayIndex) => (
                  <div key={dayIndex} className="border border-gray-200 rounded-lg p-3">
                    <div className="flex items-center justify-between mb-2">
                      <label className="font-medium text-gray-700">Day:</label>
                      <select
                        value={daySlot.day}
                        onChange={(e) => {
                          const newPreferredSlots = [...formData.preferred_slots];
                          newPreferredSlots[dayIndex] = { ...newPreferredSlots[dayIndex], day: e.target.value };
                          setFormData({ ...formData, preferred_slots: newPreferredSlots });
                        }}
                        className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                      >
                        {days.map((day) => (
                          <option key={day} value={day}>{day}</option>
                        ))}
                      </select>
                      <button
                        type="button"
                        onClick={() => {
                          const newPreferredSlots = [...formData.preferred_slots];
                          newPreferredSlots.splice(dayIndex, 1);
                          setFormData({ ...formData, preferred_slots: newPreferredSlots });
                        }}
                        className="p-1 text-red-600 hover:bg-red-100 rounded"
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>

                    <div className="space-y-2">
                      {daySlot.slots.map((slot, slotIndex) => (
                        <div key={slotIndex} className="flex items-center gap-2 mb-2 p-2 bg-gray-50 rounded">
                          <input
                            type="time"
                            value={slot.start}
                            onChange={(e) => {
                              const newPreferredSlots = [...formData.preferred_slots];
                              newPreferredSlots[dayIndex] = {
                                ...newPreferredSlots[dayIndex],
                                slots: [...newPreferredSlots[dayIndex].slots.map((s, i) =>
                                  i === slotIndex ? { ...s, start: e.target.value } : s
                                )]
                              };
                              setFormData({ ...formData, preferred_slots: newPreferredSlots });
                            }}
                            className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                          />
                          <span className="text-gray-500">to</span>
                          <input
                            type="time"
                            value={slot.end}
                            onChange={(e) => {
                              const newPreferredSlots = [...formData.preferred_slots];
                              newPreferredSlots[dayIndex] = {
                                ...newPreferredSlots[dayIndex],
                                slots: [...newPreferredSlots[dayIndex].slots.map((s, i) =>
                                  i === slotIndex ? { ...s, end: e.target.value } : s
                                )]
                              };
                              setFormData({ ...formData, preferred_slots: newPreferredSlots });
                            }}
                            className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                          />
                          <button
                            type="button"
                            onClick={() => {
                              const newPreferredSlots = [...formData.preferred_slots];
                              newPreferredSlots[dayIndex] = {
                                ...newPreferredSlots[dayIndex],
                                slots: [...newPreferredSlots[dayIndex].slots.filter((_, i) => i !== slotIndex)]
                              };
                              setFormData({ ...formData, preferred_slots: newPreferredSlots });
                            }}
                            className="p-1 text-red-600 hover:bg-red-100 rounded"
                          >
                            <Trash2 size={16} />
                          </button>
                        </div>
                      ))}
                      <button
                        type="button"
                        onClick={() => {
                          const newPreferredSlots = [...formData.preferred_slots];
                          newPreferredSlots[dayIndex] = {
                            ...newPreferredSlots[dayIndex],
                            slots: [...newPreferredSlots[dayIndex].slots, { start: '09:00', end: '11:00' }]
                          };
                          setFormData({ ...formData, preferred_slots: newPreferredSlots });
                        }}
                        className="flex items-center gap-2 px-3 py-2 text-sm text-blue-600 bg-blue-50 hover:bg-blue-100 rounded"
                      >
                        + Add Time Slot
                      </button>
                    </div>
                  </div>
                ))}
                <button
                  type="button"
                  onClick={() => {
                    setFormData({ ...formData, preferred_slots: [...formData.preferred_slots, { day: 'Mon', slots: [{ start: '09:00', end: '11:00' }] }] });
                  }}
                  className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors"
                >
                  + Add Day
                </button>
                {preferredIssues.map((issue, i) => (
                  <p key={i} className={`text-xs flex items-center gap-1 ${issue.severity === 'error' ? 'text-red-600' : 'text-amber-600'}`}>
                    <AlertTriangle size={12} /> {issue.message}
                  </p>
                ))}
              </div>
            </div>

            {/* Subjects */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="block text-sm font-medium text-gray-700">Subjects this teacher can teach</label>
                <div className="flex gap-3">
                  <button type="button" onClick={selectAllSubjects} className="text-sm text-blue-600 hover:text-blue-800">
                    Select all
                  </button>
                  <button type="button" onClick={clearAllSubjects} className="text-sm text-gray-500 hover:text-gray-700">
                    Clear all
                  </button>
                </div>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                {subjects.map((subject) => (
                  <button
                    key={subject.id}
                    type="button"
                    onClick={() => toggleSubject(subject.id)}
                    className={`p-2 text-left rounded-lg border transition-colors ${
                      formData.subjects.includes(subject.id)
                        ? 'bg-blue-100 border-blue-500 text-blue-700'
                        : 'bg-white border-gray-300 text-gray-700 hover:bg-gray-50'
                    }`}
                  >
                    <div className="font-medium">{subject.id}</div>
                    <div className="text-xs">{subject.name}</div>
                  </button>
                ))}
              </div>
            </div>

            <div className="flex gap-2">
              <button
                type="submit"
                disabled={blockingIssues.length > 0}
                title={blockingIssues.length > 0 ? blockingIssues[0].message : undefined}
                className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                <Save size={20} />
                {editingTeacher ? 'Update' : 'Save'}
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowForm(false);
                  setEditingTeacher(null);
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

      <DataTable
        storageKey="teachers"
        rows={teachers}
        getRowId={(t) => t.id}
        emptyMessage='No teachers defined yet. Click "Add Teacher" to get started.'
        searchPlaceholder="Search teachers"
        columns={[
          { key: 'id', header: 'ID', render: (t) => t.id },
          { key: 'name', header: 'Name', render: (t) => t.name },
          { key: 'initials', header: 'Initials', render: (t) => t.initials || '-', defaultVisible: false },
          { key: 'department', header: 'Department', render: (t) => departments.find((d) => d.id === t.department_id)?.name || t.department_id || '-' },
          { key: 'weekly', header: 'Weekly Hours', render: (t) => String(t.max_weekly_hours), defaultVisible: false },
          { key: 'daily', header: 'Max Daily', render: (t) => String(t.max_daily_classes) },
          { key: 'availability', header: 'Availability', render: (t) => `${(t.availability || []).length} window(s)`, defaultVisible: false },
          { key: 'guest', header: 'Guest', render: (t) => (t.is_guest_from_other_dept ? 'Yes' : 'No') },
        ]}
        actions={(teacher) => (
          <>
            <button onClick={() => handleEdit(teacher)} className="p-1 text-blue-600 hover:bg-blue-100 rounded"><Edit size={16} /></button>
            <button onClick={() => handleDelete(teacher.id)} className="p-1 text-red-600 hover:bg-red-100 rounded"><Trash2 size={16} /></button>
          </>
        )}
      />
    </div>
  );
}
