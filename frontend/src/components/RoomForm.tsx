import { useState, useEffect } from 'react';
import { roomsApi, equipmentApi, departmentsApi, constraintsApi } from '../api/client';
import { Room, Equipment, Department } from '../types';
import { useDepartment } from '../context/DepartmentContext';
import { Plus, Edit, Trash2, Save, X, AlertTriangle } from 'lucide-react';
import { DataTable } from './DataTable';
import { HelpPopover } from './HelpPopover';
import { DEFAULT_SLOTS, ScheduleSlot } from '../utils/schedule';
import { validateWindows } from '../utils/validation';

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const slugify = (value: string) => value.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');

const emptyForm = (departmentId: string) => ({
  id: '',
  name: '',
  type: 'lecture' as 'lecture' | 'lab' | 'seminar',
  capacity: 60 as number | '',
  equipment: [] as string[],
  department_id: departmentId,
  shared_with_departments: [] as string[],
  availability: [] as Array<{ day: string; start: string; end: string }>
});

export function RoomForm() {
  const { departmentId } = useDepartment();
  const [rooms, setRooms] = useState<Room[]>([]);
  const [equipmentCatalog, setEquipmentCatalog] = useState<Equipment[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [scheduleSlots, setScheduleSlots] = useState<ScheduleSlot[]>(DEFAULT_SLOTS);
  const [showForm, setShowForm] = useState(false);
  const [editingRoom, setEditingRoom] = useState<Room | null>(null);
  const [formData, setFormData] = useState(emptyForm(''));
  const [error, setError] = useState('');

  const availabilityIssues = validateWindows(formData.availability, scheduleSlots);
  const blockingIssues = availabilityIssues.filter((i) => i.severity === 'error');

  useEffect(() => {
    fetchRooms();
    fetchEquipment();
    departmentsApi.list().then((res) => setDepartments(res.data)).catch(() => setDepartments([]));
    constraintsApi.listTimeSlots().then((res) => setScheduleSlots(res.data.length ? res.data : DEFAULT_SLOTS)).catch(() => {});
  }, []);

  const fetchRooms = async () => {
    try {
      const response = await roomsApi.list();
      setRooms(response.data);
    } catch (error) {
      console.error('Failed to fetch rooms:', error);
    }
  };

  const fetchEquipment = async () => {
    try {
      const response = await equipmentApi.list();
      setEquipmentCatalog(response.data);
    } catch (error) {
      console.error('Failed to fetch equipment:', error);
    }
  };

  const addEquipment = async (name: string) => {
    const id = slugify(name);
    if (!id || equipmentCatalog.some((e) => e.id === id)) return id;
    try {
      const response = await equipmentApi.create({ id, name: name.trim() });
      setEquipmentCatalog([...equipmentCatalog, response.data]);
    } catch (error) {
      console.error('Failed to add equipment:', error);
    }
    return id;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (blockingIssues.length > 0) {
      setError(blockingIssues[0].message);
      return;
    }
    try {
      if (editingRoom) {
        await roomsApi.update(editingRoom.id, formData);
      } else {
        await roomsApi.create(formData);
      }
      setShowForm(false);
      setEditingRoom(null);
      setFormData(emptyForm(departmentId || ''));
      fetchRooms();
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Could not save this room.');
    }
  };

  const handleEdit = (room: Room) => {
    setEditingRoom(room);
    setFormData({
      id: room.id,
      name: room.name,
      type: room.type as 'lecture' | 'lab' | 'seminar',
      capacity: room.capacity,
      equipment: room.equipment || [],
      department_id: room.department_id || '',
      shared_with_departments: room.shared_with_departments || [],
      availability: room.availability || []
    });
    setShowForm(true);
  };

  const handleDelete = async (id: string) => {
    if (window.confirm('Are you sure you want to delete this room?')) {
      try {
        await roomsApi.delete(id);
        fetchRooms();
      } catch (error) {
        console.error('Failed to delete room:', error);
      }
    }
  };

  const toggleShared = (deptId: string) => {
    setFormData((current) => ({
      ...current,
      shared_with_departments: current.shared_with_departments.includes(deptId)
        ? current.shared_with_departments.filter((id) => id !== deptId)
        : [...current.shared_with_departments, deptId],
    }));
  };

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold">Rooms</h3>
        <button
          onClick={() => {
            setShowForm(true);
            setEditingRoom(null);
            setFormData(emptyForm(departmentId || ''));
          }}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          <Plus size={20} />
          Add Room
        </button>
      </div>

      {error && <p className="mb-4 rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">{error}</p>}

      {showForm && (
        <div className="mb-6 p-4 border border-gray-200 rounded-lg bg-gray-50">
          <form onSubmit={handleSubmit} className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Room ID</label>
              <input
                type="text"
                value={formData.id}
                onChange={(e) => setFormData({ ...formData, id: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                placeholder="e.g., lh101"
                required
                disabled={!!editingRoom}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Room Name</label>
              <input
                type="text"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                placeholder="e.g., LH-101"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Room Type</label>
              <select
                value={formData.type}
                onChange={(e) => setFormData({ ...formData, type: e.target.value as any })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              >
                <option value="lecture">Lecture Hall</option>
                <option value="lab">Lab</option>
                <option value="seminar">Seminar Hall</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Capacity</label>
              <input
                type="number"
                min="1"
                value={formData.capacity}
                onChange={(e) => setFormData({
                  ...formData,
                  capacity: e.target.value === '' ? '' : Number(e.target.value),
                })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Owning department</label>
              <select
                value={formData.department_id}
                onChange={(e) => setFormData({ ...formData, department_id: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              >
                <option value="">Shared / institution-wide</option>
                {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
              <div className="mt-1"><HelpPopover>Leave this as "Shared" for central lecture halls or labs any department can book. Pick a department for a room that belongs to it - other departments can still use it if you lend it below.</HelpPopover></div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Also lent to</label>
              <div className="flex flex-wrap gap-2">
                {departments.filter((d) => d.id !== formData.department_id).map((d) => {
                  const selected = formData.shared_with_departments.includes(d.id);
                  return (
                    <button
                      key={d.id} type="button" onClick={() => toggleShared(d.id)}
                      className={`px-2 py-1 text-xs rounded-full border ${selected ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-700 border-gray-300'}`}
                    >
                      {d.name}
                    </button>
                  );
                })}
                {departments.length <= 1 && <p className="text-xs text-gray-400">Add another department to lend this room to it.</p>}
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Equipment</label>
              <div className="flex flex-wrap gap-2 mb-2">
                {equipmentCatalog.map((eq) => {
                  const selected = formData.equipment.includes(eq.id);
                  return (
                    <button
                      key={eq.id} type="button"
                      onClick={() => setFormData({
                        ...formData,
                        equipment: selected ? formData.equipment.filter((id) => id !== eq.id) : [...formData.equipment, eq.id],
                      })}
                      className={`px-2 py-1 text-xs rounded-full border ${selected ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-700 border-gray-300'}`}
                    >
                      {eq.name}
                    </button>
                  );
                })}
              </div>
              <input
                type="text" placeholder="Add new equipment and press Enter"
                className="w-full px-2 py-1 text-sm border border-gray-300 rounded"
                onKeyDown={async (e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    const input = e.currentTarget;
                    const id = await addEquipment(input.value);
                    if (id) setFormData((prev) => ({ ...prev, equipment: [...prev.equipment, id] }));
                    input.value = '';
                  }
                }}
              />
            </div>

            {/* Room Availability */}
            <div className="md:col-span-2">
              <label className="block text-sm font-medium text-gray-700 mb-1">Availability</label>
              <div className="space-y-2">
                {formData.availability.map((slot, index) => (
                  <div key={index} className="flex items-center gap-2 mb-2">
                    <select
                      value={slot.day}
                      onChange={(e) => {
                        const newAvailability = [...formData.availability];
                        newAvailability[index] = { ...newAvailability[index], day: e.target.value };
                        setFormData({ ...formData, availability: newAvailability });
                      }}
                      className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    >
                      {DAYS.map((day) => (
                        <option key={day} value={day}>{day}</option>
                      ))}
                    </select>
                    <input
                      type="time"
                      value={slot.start}
                      onChange={(e) => {
                        const newAvailability = [...formData.availability];
                        newAvailability[index] = { ...newAvailability[index], start: e.target.value };
                        setFormData({ ...formData, availability: newAvailability });
                      }}
                      className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    />
                    <span className="text-gray-500">to</span>
                    <input
                      type="time"
                      value={slot.end}
                      onChange={(e) => {
                        const newAvailability = [...formData.availability];
                        newAvailability[index] = { ...newAvailability[index], end: e.target.value };
                        setFormData({ ...formData, availability: newAvailability });
                      }}
                      className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    />
                    <button
                      type="button"
                      onClick={() => {
                        const newAvailability = [...formData.availability];
                        newAvailability.splice(index, 1);
                        setFormData({ ...formData, availability: newAvailability });
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
                    setFormData({ ...formData, availability: [...formData.availability, { day: 'Mon', start: '08:00', end: '18:00' }] });
                  }}
                  className="flex items-center gap-2 px-3 py-2 text-sm text-blue-600 bg-blue-50 hover:bg-blue-100 rounded"
                >
                  + Add Availability Slot
                </button>
                {formData.availability.length > 0 && (
                  <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
                    Adding a window means the room may ONLY be used then - it becomes unavailable at every other time.
                  </p>
                )}
                {availabilityIssues.map((issue, i) => (
                  <p key={i} className={`text-xs flex items-center gap-1 ${issue.severity === 'error' ? 'text-red-600' : 'text-amber-600'}`}>
                    <AlertTriangle size={12} /> {issue.message}
                  </p>
                ))}
              </div>
            </div>

            <div className="md:col-span-2 flex gap-2">
              <button
                type="submit"
                disabled={blockingIssues.length > 0}
                title={blockingIssues.length > 0 ? blockingIssues[0].message : undefined}
                className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                <Save size={20} />
                {editingRoom ? 'Update' : 'Save'}
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowForm(false);
                  setEditingRoom(null);
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
        storageKey="rooms"
        rows={rooms}
        getRowId={(r) => r.id}
        emptyMessage='No rooms defined yet. Click "Add Room" to get started.'
        searchPlaceholder="Search rooms"
        columns={[
          { key: 'id', header: 'ID', render: (r) => r.id },
          { key: 'name', header: 'Name', render: (r) => r.name },
          { key: 'type', header: 'Type', render: (r) => <span className="capitalize">{r.type}</span> },
          { key: 'capacity', header: 'Capacity', render: (r) => String(r.capacity) },
          {
            key: 'equipment', header: 'Equipment',
            render: (r) => (r.equipment || []).map((id) => equipmentCatalog.find((e) => e.id === id)?.name || id).join(', ') || '-',
          },
          { key: 'department', header: 'Department', render: (r) => departments.find((d) => d.id === r.department_id)?.name || 'Shared', defaultVisible: false },
          {
            key: 'shared', header: 'Shared with', defaultVisible: false,
            render: (r) => (r.shared_with_departments || []).map((id) => departments.find((d) => d.id === id)?.name || id).join(', ') || '-',
          },
          { key: 'availability', header: 'Availability', render: (r) => (r.availability?.length ? `${r.availability.length} window(s)` : 'Always'), defaultVisible: false },
        ]}
        actions={(room) => (
          <>
            <button onClick={() => handleEdit(room)} className="p-1 text-blue-600 hover:bg-blue-100 rounded"><Edit size={16} /></button>
            <button onClick={() => handleDelete(room.id)} className="p-1 text-red-600 hover:bg-red-100 rounded"><Trash2 size={16} /></button>
          </>
        )}
      />
    </div>
  );
}
