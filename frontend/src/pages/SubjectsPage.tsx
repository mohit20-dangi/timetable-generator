import { SubjectForm } from '../components/SubjectForm';

export function SubjectsPage() {
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Subjects</h1>
        <p className="text-gray-600">Define subjects, their L-T-P hours, and requirements.</p>
      </div>
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <SubjectForm />
      </div>
    </div>
  );
}
