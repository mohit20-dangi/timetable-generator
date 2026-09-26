import { BulkExcelImport } from '../components/BulkExcelImport';

/** Moved to the end of Setup (Phase 3.2) - an accelerator for admins who
 * already understand the data model, not the second thing a new admin sees. */
export function ImportPage() {
  return (
    <div>
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <BulkExcelImport />
      </div>
    </div>
  );
}
