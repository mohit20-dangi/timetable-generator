import { AIAssistantPanel } from '../components/AIAssistantPanel';
import { useDepartment } from '../context/DepartmentContext';

export function AISetupPage() {
  const { departmentId } = useDepartment();
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">AI Setup Assistant</h1>
        <p className="text-gray-600">Edit teacher limits and add scheduling rules in plain English. Changes are saved to your setup only after you review and apply them.</p>
      </div>
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        {departmentId
          ? <AIAssistantPanel departmentId={departmentId} />
          : <p className="text-sm text-gray-600">Select a department first - the assistant edits one department's setup at a time.</p>}
      </div>
    </div>
  );
}
