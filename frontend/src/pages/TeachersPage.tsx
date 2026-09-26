import { TeacherForm } from '../components/TeacherForm';

export function TeachersPage() {
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Teachers</h1>
        <p className="text-gray-600">Define teachers, their subjects, and when they can teach.</p>
      </div>
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <TeacherForm />
      </div>
    </div>
  );
}
