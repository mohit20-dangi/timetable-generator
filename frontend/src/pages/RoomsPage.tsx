import { RoomForm } from '../components/RoomForm';

export function RoomsPage() {
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Rooms</h1>
        <p className="text-gray-600">Define rooms, their equipment, and availability.</p>
      </div>
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <RoomForm />
      </div>
    </div>
  );
}
