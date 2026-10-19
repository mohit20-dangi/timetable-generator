import { useState } from 'react';
import { AlertCircle, CheckCircle, Download, FileSpreadsheet, Upload } from 'lucide-react';
import { bulkImportApi } from '../api/client';
import { useDepartment } from '../context/DepartmentContext';

// "college_load" = the department's own teaching-load workbook, converted
// server-side; `warnings` are the assumptions the conversion made.
type SourceInfo = {
  format: 'template' | 'college_load';
  source_sheet?: string;
  department_name?: string;
  warnings: string[];
};

type ImportResult = SourceInfo & {
  message: string;
  sheets: Record<string, number>;
  created: number;
  updated: number;
  relations_created: number;
};

type PreviewResult = SourceInfo & {
  message: string;
  sheets: Record<string, number>;
  total_rows: number;
  linked_updates: number;
};

function SourceNotes({ source }: { source: SourceInfo }) {
  if (source.format !== 'college_load') return null;
  return (
    <div className="mt-2">
      <p>
        Read as a department load workbook, using the allotment sheet <strong>{source.source_sheet}</strong>,
        into department <strong>{source.department_name}</strong>.
      </p>
      {source.warnings.length > 0 && (
        <ul className="mt-1 list-disc pl-5 space-y-0.5">
          {source.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function BulkExcelImport() {
  const { departmentId } = useDepartment();
  const [file, setFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [error, setError] = useState('');

  const download = async (fetchFile: () => Promise<{ data: Blob }>, filename: string) => {
    try {
      const response = await fetchFile();
      const url = URL.createObjectURL(response.data);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      link.click();
      URL.revokeObjectURL(url);
    } catch {
      setError('Could not download the Excel template.');
    }
  };

  const handleUpload = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!file) {
      setError('Choose an .xlsx or .xlsm file first.');
      return;
    }
    setIsUploading(true);
    setError('');
    setResult(null);
    setPreview(null);
    try {
      const response = await bulkImportApi.previewExcel(file, departmentId);
      setPreview(response.data);
    } catch (uploadError: any) {
      const detail = uploadError?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'The workbook could not be validated.');
    } finally {
      setIsUploading(false);
    }
  };

  const handleConfirmImport = async () => {
    if (!file || !preview) return;
    setIsUploading(true);
    setError('');
    try {
      const response = await bulkImportApi.uploadExcel(file, departmentId);
      setResult(response.data);
      setPreview(null);
    } catch (uploadError: any) {
      const detail = uploadError?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'The workbook could not be imported.');
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="max-w-3xl">
      <div className="flex items-start gap-4 mb-6">
        <div className="p-3 rounded-xl bg-green-50 text-green-700">
          <FileSpreadsheet size={28} />
        </div>
        <div>
          <h3 className="text-lg font-semibold text-gray-900">Load setup from Excel</h3>
          <p className="text-sm text-gray-600 mt-1">
            Upload the department's teaching-load workbook as it is. Existing records are updated and missing
            ones created, in the department you're working in.
          </p>
        </div>
      </div>

      <div className="rounded-lg border border-blue-100 bg-blue-50 p-4 mb-6 text-sm text-blue-900">
        <p className="font-medium">The workbook has six sheets</p>
        <ol className="mt-1 list-decimal pl-5 space-y-0.5">
          <li><strong>Faculty List</strong> - each teacher's name and initials.</li>
          <li><strong>Subject Choice</strong> - what each teacher can teach. Used for subjects nobody is allocated to.</li>
          <li>
            <strong>Load Calculation</strong> - every class's subjects with theory, tutorial and practical periods,
            batches and faculty per session.
          </li>
          <li>
            <strong>Faculty wise subject allocation</strong> - the final list. A teacher listed here teaches exactly
            those subjects; a secondary column lists teachers who only assist.
          </li>
          <li><strong>First Year Load</strong> - hours a teacher gives to first year; taken off their weekly hours.</li>
          <li>
            <strong>Elective</strong> - the options of each elective. An NPTEL option needs no teacher: it gets
            self-study periods in the first or last period of the day.
          </li>
        </ol>
        <p className="mt-2">
          The department's own load file (with <strong>Subject_facult_&lt;date&gt;</strong> sheets) is accepted as it is
          too; its newest revision is used.
        </p>
        <p className="mt-2">
          Rooms, the bell schedule and term dates aren't in this file - set them up separately. Re-uploading a
          newer revision updates the allotments to match it; nothing you added by hand is deleted.
        </p>
      </div>

      <div className="flex flex-wrap gap-3 mb-6">
        <button
          type="button"
          onClick={() => download(bulkImportApi.downloadCollegeTemplate, 'department-load-template.xlsx')}
          className="flex items-center gap-2 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors"
        >
          <Download size={18} />
          Download department load template
        </button>
      </div>

      <form onSubmit={handleUpload} className="border-2 border-dashed border-gray-300 rounded-xl p-6">
        <label className="block cursor-pointer">
          <span className="text-sm font-medium text-gray-700">Select workbook</span>
          <input
            type="file"
            accept=".xlsx,.xlsm"
            onChange={(event) => {
              setFile(event.target.files?.[0] || null);
              setError('');
              setResult(null);
            }}
            className="block w-full mt-2 text-sm text-gray-600 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
          />
        </label>
        {file && <p className="mt-3 text-sm text-gray-600">Selected: {file.name}</p>}
        <button
          type="submit"
          disabled={isUploading || !file}
          className="mt-5 flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <Upload size={18} />
          {isUploading ? 'Validating...' : 'Validate workbook'}
        </button>
      </form>

      <details className="mt-4 rounded-lg border border-gray-200 p-4 text-sm text-gray-700">
        <summary className="cursor-pointer font-medium text-gray-800">
          Advanced: the app's own template (one sheet per table)
        </summary>
        <p className="mt-2">
          The same upload box also accepts a workbook with one sheet per table - AcademicYears, Sections, Subjects,
          Teachers, Rooms, SectionSubjects, TeacherSubjects, LabBatches, Prerequisites and TimeSlots. You can include
          only the sheets you need. Fields with several values (a teacher's free periods, a room's equipment, an
          elective group's subjects, ...) are their own linking sheet, one plain row per value, referencing the
          parent by id (TeacherAvailability, RoomEquipment, AcademicYearLunchWindows, ElectiveGroupSubjects).
        </p>
        <button
          type="button"
          onClick={() => download(bulkImportApi.downloadTemplate, 'timetable-import-template.xlsx')}
          className="mt-3 flex items-center gap-2 px-3 py-1.5 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50"
        >
          <Download size={16} />
          Download the app template
        </button>
      </details>

      {preview && (
        <div className="mt-4 rounded-lg bg-amber-50 border border-amber-200 p-4 text-sm text-amber-900">
          <p className="font-medium">{preview.message}</p>
          <p className="mt-1">{preview.total_rows} row(s) are ready across {Object.keys(preview.sheets).length} sheet(s).</p>
          <p className="mt-1">Rows: {Object.entries(preview.sheets).map(([name, count]) => `${name} (${count})`).join(', ')}.</p>
          <SourceNotes source={preview} />
          {preview.linked_updates > 0 && (
            <p className="mt-1">
              Plus {preview.linked_updates} linking-sheet update(s) to existing records not otherwise in this workbook.
            </p>
          )}
          <button
            type="button"
            onClick={handleConfirmImport}
            disabled={isUploading}
            className="mt-3 px-4 py-2 bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-50"
          >
            {isUploading ? 'Importing...' : 'Confirm and import'}
          </button>
        </div>
      )}

      {error && (
        <div className="mt-4 flex items-start gap-2 rounded-lg bg-red-50 border border-red-200 p-4 text-sm text-red-800">
          <AlertCircle size={18} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {result && (
        <div className="mt-4 rounded-lg bg-green-50 border border-green-200 p-4 text-sm text-green-900">
          <div className="flex items-center gap-2 font-medium">
            <CheckCircle size={18} />
            {result.message}
          </div>
          <p className="mt-2">Created {result.created}, updated {result.updated}, relationships added {result.relations_created}.</p>
          <p className="mt-1 text-green-800">
            Rows read: {Object.entries(result.sheets).map(([name, count]) => `${name} (${count})`).join(', ')}.
          </p>
          <SourceNotes source={result} />
        </div>
      )}
    </div>
  );
}
