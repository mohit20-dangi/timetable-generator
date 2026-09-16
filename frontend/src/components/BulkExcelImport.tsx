import { useState } from 'react';
import { AlertCircle, CheckCircle, Download, FileSpreadsheet, Upload } from 'lucide-react';
import { bulkImportApi } from '../api/client';

type ImportResult = {
  message: string;
  sheets: Record<string, number>;
  created: number;
  updated: number;
  relations_created: number;
};

type PreviewResult = {
  message: string;
  sheets: Record<string, number>;
  total_rows: number;
};

export function BulkExcelImport() {
  const [file, setFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [error, setError] = useState('');

  const handleDownloadTemplate = async () => {
    try {
      const response = await bulkImportApi.downloadTemplate();
      const url = URL.createObjectURL(response.data);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'timetable-import-template.xlsx';
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
      const response = await bulkImportApi.previewExcel(file);
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
      const response = await bulkImportApi.uploadExcel(file);
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
            Import your timetable data in one workbook. Existing records with the same IDs are updated;
            missing records are created.
          </p>
        </div>
      </div>

      <div className="rounded-lg border border-blue-100 bg-blue-50 p-4 mb-6 text-sm text-blue-900">
        Supported sheets: AcademicYears, Sections, Subjects, Teachers, Rooms, SectionSubjects,
        TeacherSubjects, LabBatches, Prerequisites, and TimeSlots. You can upload only the sheets you need.
      </div>

      <div className="flex flex-wrap gap-3 mb-6">
        <button
          type="button"
          onClick={handleDownloadTemplate}
          className="flex items-center gap-2 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors"
        >
          <Download size={18} />
          Download Excel template
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

      {preview && (
        <div className="mt-4 rounded-lg bg-amber-50 border border-amber-200 p-4 text-sm text-amber-900">
          <p className="font-medium">{preview.message}</p>
          <p className="mt-1">{preview.total_rows} row(s) are ready across {Object.keys(preview.sheets).length} sheet(s).</p>
          <p className="mt-1">Rows: {Object.entries(preview.sheets).map(([name, count]) => `${name} (${count})`).join(', ')}.</p>
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
        </div>
      )}
    </div>
  );
}
