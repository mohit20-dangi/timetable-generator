import { LabRotationManager } from '../components/LabRotationManager';

export function LabRotationsPage() {
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Lab Rotations</h1>
        <p className="text-gray-600">
          Run several of a section's labs at the same time with a different batch in each, swapping
          round by round - so each lab only needs one teacher at a time.
        </p>
      </div>
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <LabRotationManager />
      </div>
    </div>
  );
}
