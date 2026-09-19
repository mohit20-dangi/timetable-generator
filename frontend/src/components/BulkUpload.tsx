import { useRef, useState } from 'react';
import { Upload, Download, X } from 'lucide-react';
import api from '../api/client';

interface BulkUploadResult {
  created: string[];
  errors: { row: number; id: string | null; error: string }[];
}

interface BulkUploadProps {
  label: string;
  uploadPath: string;   // e.g. '/years/bulk'
  templatePath: string; // e.g. '/years/bulk/template'
  onDone: () => void;
}

export function BulkUpload({ label, uploadPath, templatePath, onDone }: BulkUploadProps) {
  const [open, setOpen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<BulkUploadResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const handleDownloadTemplate = async () => {
    const response = await api.get(templatePath, { responseType: 'blob' });
    const url = window.URL.createObjectURL(new Blob([response.data]));
    const link = document.createElement('a');
    link.href = url;
    link.download = `${label.toLowerCase().replace(/\s+/g, '_')}_template.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.URL.revokeObjectURL(url);
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    setError(null);
    setResult(null);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const response = await api.post(uploadPath, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setResult(response.data);
      onDone();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Upload failed');
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = '';
    }
  };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-2 px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors"
      >
        <Upload size={20} />
        Bulk Upload
      </button>
    );
  }

  return (
    <div className="mb-6 p-4 border border-gray-200 rounded-lg bg-gray-50">
      <div className="flex justify-between items-center mb-3">
        <h4 className="font-medium text-gray-700">Bulk Upload {label}</h4>
        <button onClick={() => { setOpen(false); setResult(null); setError(null); }} className="p-1 text-gray-500 hover:bg-gray-200 rounded">
          <X size={18} />
        </button>
      </div>
      <p className="text-sm text-gray-600 mb-3">
        Upload a CSV or Excel file with one row per {label.toLowerCase()}. Fields that take multiple values
        (e.g. equipment, subject IDs) use a semicolon-separated list in a single cell.
      </p>
      <div className="flex items-center gap-3 mb-3">
        <button
          onClick={handleDownloadTemplate}
          className="flex items-center gap-2 px-3 py-2 text-sm text-blue-600 bg-blue-50 hover:bg-blue-100 rounded-lg"
        >
          <Download size={16} />
          Download Template
        </button>
        <label className="flex items-center gap-2 px-3 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 cursor-pointer">
          <Upload size={16} />
          {uploading ? 'Uploading...' : 'Choose File'}
          <input
            ref={fileInput}
            type="file"
            accept=".csv,.xlsx,.xls"
            className="hidden"
            onChange={handleFileChange}
            disabled={uploading}
          />
        </label>
      </div>

      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">{error}</div>
      )}

      {result && (
        <div className="space-y-2">
          <div className="p-3 bg-green-50 border border-green-200 rounded-lg text-sm text-green-700">
            Created {result.created.length} record{result.created.length === 1 ? '' : 's'}
            {result.created.length > 0 && `: ${result.created.join(', ')}`}
          </div>
          {result.errors.length > 0 && (
            <div className="p-3 bg-red-50 border border-red-200 rounded-lg">
              <p className="text-sm font-medium text-red-800 mb-1">{result.errors.length} row(s) failed:</p>
              <ul className="text-sm text-red-700 list-disc list-inside">
                {result.errors.map((e, i) => (
                  <li key={i}>Row {e.row}{e.id ? ` (${e.id})` : ''}: {e.error}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
