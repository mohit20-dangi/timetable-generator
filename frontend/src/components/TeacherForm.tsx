import { useState, useEffect } from 'react';
import { teachersApi, subjectsApi } from '../api/client';
import { Teacher, Subject } from '../types';
import { Plus, Edit, Trash2, Save, X } from 'lucide-react';
import { BulkUpload } from './BulkUpload';

export function TeacherForm() {
  const [teachers, setTeachers] = useState<Teacher[]>([]);
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editingTeacher, setEditingTeacher] = useState<Teacher | null>(null);
  const [formData, setFormData] = useState({
    id: '',
    name: '',
    department: '',
    max_continuous_classes: 3,
    max_daily_classes: 5,
    availability: [] as Array<{ day: string; start: string; end: string }>,
    preferred_slots: [] as Array<{ day: string; slots: Array<{ start: string; end: string }> }>,
    is_guest_from_other_dept: false,
    subject_ids: [] as string[]
  });

  const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

  useEffect(() => {
    fetchTeachers();
    fetchSubjects();
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
    try {
      if (editingTeacher) {
        // Update logic would go here
      } else {
        await teachersApi.create(formData);
      }
      setShowForm(false);
      setEditingTeacher(null);
      resetForm();
      fetchTeachers();
    } catch (error) {
      console.error('Failed to save teacher:', error);
    }
  };

  const resetForm = () => {
    setFormData({
      id: '', name: '', department: '',
      max_continuous_classes: 3, max_daily_classes: 5,
      availability: [], preferred_slots: [],
      is_guest_from_other_dept: false, subject_ids: []
    });
  };

  const handleEdit = (teacher: Teacher) => {
    setEditingTeacher(teacher);
    setFormData({
      id: teacher.id,
      name: teacher.name,
      department: teacher.department || '',
      max_continuous_classes: teacher.max_continuous_classes,
      max_daily_classes: teacher.max_daily_classes,
      availability: teacher.availability || [],
      preferred_slots: teacher.preferred_slots || [],
      is_guest_from_other_dept: teacher.is_guest_from_other_dept,
      subject_ids: teacher.subject_ids || []
    });
    setShowForm(true);
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
    if (formData.subject_ids.includes(subjectId)) {
      setFormData({
        ...formData,
        subject_ids: formData.subject_ids.filter(id => id !== subjectId)
      });
    } else {
      setFormData({
        ...formData,
        subject_ids: [...formData.subject_ids, subjectId]
      });
    }
  };

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold">Teachers</h3>
        <div className="flex gap-2">
          <BulkUpload label="Teachers" uploadPath="/teachers/bulk" templatePath="/teachers/bulk/template" onDone={fetchTeachers} />
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
      </div>

      {showForm && (
        <div className="mb-6 p-4 border border-gray-200 rounded-lg bg-gray-50">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Teacher ID</label>
                <input
                  type="text"
                  value={formData.id}
                  onChange={(e) => setFormData({ ...formData, id: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  placeholder="e.g., t1"
                  required
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
                <label className="block text-sm font-medium text-gray-700 mb-1">Department</label>
                <input
                  type="text"
                  value={formData.department}
                  onChange={(e) => setFormData({ ...formData, department: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Max Continuous Classes</label>
                <input
                  type="number"
                  min="1"
                  value={formData.max_continuous_classes}
                  onChange={(e) => setFormData({ ...formData, max_continuous_classes: parseInt(e.target.value) })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Max Daily Classes</label>
                <input
                  type="number"
                  min="1"
                  value={formData.max_daily_classes}
                  onChange={(e) => setFormData({ ...formData, max_daily_classes: parseInt(e.target.value) })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
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

            {/* Availability */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="block text-sm font-medium text-gray-700">Availability</label>
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
            </div>

            {/* Preferred Time Slots (Multiple Intervals) */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Preferred Teaching Times</label>
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
              </div>
            </div>

            {/* Subjects */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Subjects this teacher can teach</label>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                {subjects.map((subject) => (
                  <button
                    key={subject.id}
                    type="button"
                    onClick={() => toggleSubject(subject.id)}
                    className={`p-2 text-left rounded-lg border transition-colors ${
                      formData.subject_ids.includes(subject.id)
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
                className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors"
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

      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr className="bg-gray-100">
              <th className="text-left px-4 py-2 font-medium text-gray-700">ID</th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">Name</th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">Department</th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">Max Daily</th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">Guest</th>
              <th className="text-right px-4 py-2 font-medium text-gray-700">Actions</th>
            </tr>
          </thead>
          <tbody>
            {teachers.map((teacher) => (
              <tr key={teacher.id} className="border-b border-gray-200">
                <td className="px-4 py-2">{teacher.id}</td>
                <td className="px-4 py-2">{teacher.name}</td>
                <td className="px-4 py-2">{teacher.department || '-'}</td>
                <td className="px-4 py-2">{teacher.max_daily_classes}</td>
                <td className="px-4 py-2">{teacher.is_guest_from_other_dept ? 'Yes' : 'No'}</td>
                <td className="px-4 py-2 text-right">
                  <button
                    onClick={() => handleEdit(teacher)}
                    className="p-1 text-blue-600 hover:bg-blue-100 rounded"
                  >
                    <Edit size={16} />
                  </button>
                  <button
                    onClick={() => handleDelete(teacher.id)}
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

      {teachers.length === 0 && (
        <div className="text-center py-8 text-gray-500">
          No teachers defined yet. Click "Add Teacher" to get started.
        </div>
      )}
    </div>
  );
}