import { FirstYearImport } from '../components/FirstYearImport';

/** The first-year timetable is allotted centrally, so the solver never sees
 * it - but it books our teachers and rooms. This step turns the central PDF
 * into hard locks for years 2-4. */
export function FirstYearImportPage() {
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6">
      <FirstYearImport />
    </div>
  );
}
