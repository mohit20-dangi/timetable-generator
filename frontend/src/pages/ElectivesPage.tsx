import { ElectiveGroupManager } from '../components/ElectiveGroupManager';

export function ElectivesPage() {
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Electives</h1>
        <p className="text-gray-600">Mark which elective options are actually offered this term.</p>
      </div>
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <ElectiveGroupManager />
      </div>
    </div>
  );
}
