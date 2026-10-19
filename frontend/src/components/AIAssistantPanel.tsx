import { useState } from 'react';
import { aiAgentApi } from '../api/client';
import { AgentProposedAction } from '../types';
import { Sparkles, Send, CheckCircle, AlertCircle, Trash2 } from 'lucide-react';

interface Props {
  departmentId: string;
}

/**
 * The tool-calling agent's UI. Deliberately a two-step flow, matching the
 * backend's plan/apply split: the agent can only ever PROPOSE changes
 * (POST /api/ai/agent/plan), never write to the database. Nothing is
 * applied until the admin reviews the plan here and clicks Apply, which
 * calls POST /api/ai/agent/apply with the (possibly edited) action list -
 * never re-asking the model. See app/services/ai_agent.py's module
 * docstring on the backend for why this boundary is non-negotiable.
 */
// The server's detail already says what failed and why; the fallbacks cover
// the cases where no server answer exists at all.
function describeError(err: any, prefix: string): string {
  const detail = err.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return `${prefix}: ${detail.map((d: any) => d.msg).join('; ')}`;
  if (err.request) return `${prefix}: could not reach the server. Check your connection and try again. Nothing was changed.`;
  return `${prefix}: ${err.message}`;
}

export function AIAssistantPanel({ departmentId }: Props) {
  const [instruction, setInstruction] = useState('');
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<string | null>(null);
  const [actions, setActions] = useState<AgentProposedAction[]>([]);
  const [applied, setApplied] = useState(false);
  const [appliedCount, setAppliedCount] = useState(0);
  const [skipped, setSkipped] = useState<string[]>([]);

  const runPlan = async () => {
    if (!instruction.trim() || !departmentId) return;
    setLoading(true);
    setError(null);
    setSummary(null);
    setActions([]);
    setApplied(false);
    setSkipped([]);
    try {
      const response = await aiAgentApi.plan(departmentId, instruction);
      setSummary(response.data.summary);
      setActions(response.data.actions);
    } catch (err: any) {
      setError(describeError(err, 'Planning failed'));
    } finally {
      setLoading(false);
    }
  };

  const removeAction = (index: number) => {
    setActions(actions.filter((_, i) => i !== index));
  };

  const applyActions = async () => {
    if (actions.length === 0) return;
    setApplying(true);
    setError(null);
    try {
      const response = await aiAgentApi.apply(departmentId, instruction, actions);
      setSkipped(response.data.skipped || []);
      setAppliedCount(response.data.applied);
      setApplied(true);
      setActions([]);
    } catch (err: any) {
      setError(describeError(err, 'Applying failed'));
    } finally {
      setApplying(false);
    }
  };

  return (
    <div className="rounded-lg border border-purple-200 bg-purple-50 p-4">
      <h3 className="flex items-center gap-2 font-semibold text-purple-900">
        <Sparkles size={20} />
        Edit setup data with AI
      </h3>
      <p className="mt-1 text-sm text-purple-800">
        Tell it what you want changed in plain English - e.g. "Increase every teacher's max daily
        classes by 1" or "Prof. Sharma is unavailable Friday afternoons". It will propose the exact
        changes for you to review; nothing is applied until you click Apply. Once applied, the
        changes are saved to your setup data (teacher limits and scheduling rules) and recorded in
        the audit trail. To set solver priorities instead, use Scheduling Rules.
      </p>

      <div className="mt-3 flex gap-2">
        <input
          type="text" value={instruction} onChange={(e) => setInstruction(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && runPlan()}
          placeholder="What would you like to change?"
          className="flex-1 rounded-lg border border-purple-300 px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500 focus:border-transparent"
        />
        <button
          onClick={runPlan} disabled={loading || !instruction.trim()}
          className="flex items-center gap-2 rounded-lg bg-purple-600 px-4 py-2 text-sm font-medium text-white hover:bg-purple-700 disabled:opacity-50"
        >
          {loading ? <div className="h-4 w-4 animate-spin rounded-full border-b-2 border-white" /> : <Send size={16} />}
          {loading ? 'Thinking...' : 'Ask'}
        </button>
      </div>

      {error && (
        <div className="mt-3 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          <AlertCircle size={18} className="mt-0.5" />
          {error}
        </div>
      )}

      {applied && (
        <div className="mt-3 flex items-center gap-2 rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-800">
          <CheckCircle size={18} />
          {appliedCount} change{appliedCount === 1 ? '' : 's'} applied and logged to the audit trail.
        </div>
      )}

      {skipped.length > 0 && (
        <div className="mt-3 rounded-lg border border-yellow-200 bg-yellow-50 p-3 text-sm text-yellow-900">
          <p className="font-medium">{skipped.length} change{skipped.length === 1 ? ' was' : 's were'} not applied:</p>
          <ul className="list-disc pl-5">
            {skipped.map((reason) => <li key={reason}>{reason}</li>)}
          </ul>
        </div>
      )}

      {summary && (
        <div className="mt-4 rounded-lg border border-purple-200 bg-white p-3">
          <p className="text-sm text-gray-700">{summary}</p>
        </div>
      )}

      {actions.length > 0 && (
        <div className="mt-3 space-y-2">
          <p className="text-sm font-medium text-purple-900">Proposed changes - review before applying:</p>
          {actions.map((action, index) => (
            <div key={index} className="flex items-center justify-between rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm">
              <span className="text-gray-800">{action.description}</span>
              <button onClick={() => removeAction(index)} className="p-1 text-red-500 hover:bg-red-50 rounded" title="Remove this change">
                <Trash2 size={16} />
              </button>
            </div>
          ))}
          <button
            onClick={applyActions} disabled={applying}
            className="mt-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
          >
            {applying ? 'Applying...' : `Apply ${actions.length} change${actions.length === 1 ? '' : 's'}`}
          </button>
        </div>
      )}
    </div>
  );
}
