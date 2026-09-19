import { useState, useEffect } from 'react';
import { roomsApi } from '../api/client';
import { Room } from '../types';
import { Plus, Edit, Trash2, Save, X } from 'lucide-react';
import { BulkUpload } from './BulkUpload';

export function RoomForm() {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editingRoom, setEditingRoom] = useState<Room | null>(null);
  const [formData, setFormData] = useState({
    id: '',
    name: '',
    type: 'lecture' as 'lecture' | 'lab' | 'seminar',
    capacity: 60,
    equipment: [] as string[],
    shared_with_departments: [] as string[],
    availability: [] as Array<{ day: string; start: string; end: string }>
  });

  const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

  useEffect(() => {
    fetchRooms();
  }, []);

  const fetchRooms = async () => {
    try {
      const response = await roomsApi.list();
      setRooms(response.data);
    } catch (error) {
      console.error('Failed to fetch rooms:', error);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      if (editingRoom) {
        // Update logic would go here
      } else {
        await roomsApi.create(formData);
      }
      setShowForm(false);
      setEditingRoom(null);
      setFormData({
        id: '', name: '', type: 'lecture', capacity: 60,
        equipment: [], shared_with_departments: [], availability: []
      });
      fetchRooms();
    } catch (error) {
      console.error('Failed to save room:', error);
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

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold">Rooms</h3>
        <div className="flex gap-2">
          <BulkUpload label="Rooms" uploadPath="/rooms/bulk" templatePath="/rooms/bulk/template" onDone={fetchRooms} />
          <button
            onClick={() => {
              setShowForm(true);
              setEditingRoom(null);
              setFormData({
                id: '', name: '', type: 'lecture', capacity: 60,
                equipment: [], shared_with_departments: [], availability: []
              });
            }}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
          >
            <Plus size={20} />
            Add Room
          </button>
        </div>
      </div>

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
                onChange={(e) => setFormData({ ...formData, capacity: parseInt(e.target.value) })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Equipment (comma-separated)</label>
              <input
                type="text"
                value={formData.equipment.join(', ')}
                onChange={(e) => setFormData({ ...formData, equipment: e.target.value.split(',').map(s => s.trim()).filter(Boolean) })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                placeholder="e.g., computers, projector"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Shared Departments (comma-separated)</label>
              <input
                type="text"
                value={formData.shared_with_departments.join(', ')}
                onChange={(e) => setFormData({ ...formData, shared_with_departments: e.target.value.split(',').map(s => s.trim()).filter(Boolean) })}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                placeholder="e.g., CSE, IT"
              />
            </div>
            
            {/* Room Availability */}
            <div>
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
                      {days.map((day) => (
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
              </div>
            </div>
            
            <div className="md:col-span-2 flex gap-2">
              <button
                type="submit"
                className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors"
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

      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr className="bg-gray-100">
              <th className="text-left px-4 py-2 font-medium text-gray-700">ID</th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">Name</th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">Type</th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">Capacity</th>
              <th className="text-left px-4 py-2 font-medium text-gray-700">Equipment</th>
              <th className="text-right px-4 py-2 font-medium text-gray-700">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rooms.map((room) => (
              <tr key={room.id} className="border-b border-gray-200">
                <td className="px-4 py-2">{room.id}</td>
                <td className="px-4 py-2">{room.name}</td>
                <td className="px-4 py-2 capitalize">{room.type}</td>
                <td className="px-4 py-2">{room.capacity}</td>
                <td className="px-4 py-2">{room.equipment?.join(', ') || '-'}</td>
                <td className="px-4 py-2 text-right">
                  <button
                    onClick={() => handleEdit(room)}
                    className="p-1 text-blue-600 hover:bg-blue-100 rounded"
                  >
                    <Edit size={16} />
                  </button>
                  <button
                    onClick={() => handleDelete(room.id)}
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

      {rooms.length === 0 && (
        <div className="text-center py-8 text-gray-500">
          No rooms defined yet. Click "Add Room" to get started.
        </div>
      )}
    </div>
  );
}