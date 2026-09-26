import { AcademicYearForm } from '../components/AcademicYearForm';
import { SectionForm } from '../components/SectionForm';

/** Merged per Phase 3.2 - years and their sections are the same mental
 * object to an admin, and per-day lunch (Phase 2.5) lives with the year. */
export function YearsSectionsPage() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Years & Sections</h1>
        <p className="text-gray-600">Define academic years, their lunch breaks, and the sections within them.</p>
      </div>
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <AcademicYearForm />
      </div>
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <SectionForm />
      </div>
    </div>
  );
}
