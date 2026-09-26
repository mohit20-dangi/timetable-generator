import { ConstraintBuilder } from '../components/ConstraintBuilder';
import { ConstraintRulesManager } from '../components/ConstraintRulesManager';

export function SchedulingRulesPage() {
  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Scheduling Rules</h1>
        <p className="text-gray-600">Set your priorities, or describe them in plain English and let the AI assistant draft them.</p>
      </div>
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <ConstraintBuilder />
      </div>
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <ConstraintRulesManager />
      </div>
    </div>
  );
}
