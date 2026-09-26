import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { timetableApi } from '../api/client';
import { AgentProposedAction } from '../types';
import { Sparkles, Send, AlertCircle, Trash2, RefreshCw } from 'lucide-react';

interface Props {
  runId: number;
}

/**
 * Whole-timetable AI editing - "remove Cloud Computing", "give DBMS one
 * more class a week for Section B" - as opposed to EditEntryModal's AI
 * move-box, which only helps place ONE already-selected class.
 *
 * Same plan/apply split as AIAssistantPanel: the model can only ever
 * PROPOSE changes (POST .../ai-plan). Nothing is written until the admin
 * reviews the plan and clicks Apply, which forks a new run with those
 * changes and re-runs the actual solver on it (POST .../ai-apply) - a real
 * feasibility check, not a heuristic patch. See
 * app/services/timetable_ai_agent.py's module docstring on the backend.
 */
export function TimetableAIAssistant({ runId }: Props) {
  const navigate = useNavigate();
  const [instruction, setInstruction] = useState('');
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<string | null>(null);
  const [actions, setActions] = useState<AgentProposedAction[]>([]);

  const runPlan = async () => {
    if (!instruction.trim()) return;
    setLoading(true);
    setError(null);
    setSummary(null);
    setActions([]);
    try {
      const response = await timetableApi.aiPlan(runId, instruction);
      setSummary(response.data.summary);
      setActions(response.data.actions);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'The AI assistant is unavailable right now.');
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
      const response = await timetableApi.aiApply(runId, actions);
      const newRun = response.data;

      // Same poll-until-done pattern as GenerateButton - this forks a new
      // run and actually re-solves it, so it isn't done the instant this
      // call returns.
      const pollInterval = setInterval(async () => {
        try {
          const updated = await timetableApi.getRun(newRun.id);
          if (updated.data.status === 'completed') {
            clearInterval(pollInterval);
            navigate(`/runs/${newRun.id}`);
          } else if (updated.data.status === 'failed') {
            clearInterval(pollInterval);
            setApplying(false);
            setError(updated.data.llm_explanation || 'Regenerating the timetable with these changes failed.');
          }
        } catch {
          clearInterval(pollInterval);
          setApplying(false);
          setError('Failed to check the new version\'s status.');
        }
      }, 2000);
    } catch (err: any) {
      setApplying(false);
      setError(err.response?.data?.detail || 'Failed to apply the changes.');
    }
  };

  return (
    <div className="rounded-lg border border-purple-200 bg-purple-50 p-4">
      <h3 className="flex items-center gap-2 font-semibold text-purple-900">
        <Sparkles size={20} />
        AI Timetable Assistant
      </h3>
      <p className="mt-1 text-sm text-purple-800">
        Tell it what to change about this whole timetable in plain English - e.g. "Remove Cloud
        Computing" or "Give Data Structures one more class a week". It proposes changes for you to
        review; applying them regenerates the timetable as a new version through the real solver, so
        it's checked for feasibility like any other run. These changes only affect this timetable -
        they never change a subject's actual configured hours. It can't move an already-placed class
        to a new time - use "Move Class" on that class for that.
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

      {summary && (
        <div className="mt-4 rounded-lg border border-purple-200 bg-white p-3">
          <p className="text-sm text-gray-700 whitespace-pre-wrap">{summary}</p>
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
            className="mt-2 flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
          >
            {applying && <RefreshCw size={16} className="animate-spin" />}
            {applying ? 'Regenerating timetable...' : `Apply ${actions.length} change${actions.length === 1 ? '' : 's'} and regenerate`}
          </button>
        </div>
      )}
    </div>
  );
}
