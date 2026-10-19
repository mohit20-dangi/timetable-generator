import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { timetableApi } from '../api/client';
import { AgentProposedAction, EditConflict, EditOperation } from '../types';
import { Sparkles, Send, AlertCircle, Trash2, RefreshCw, Check } from 'lucide-react';
import { ApplyOutcome } from '../hooks/useTimetableEditor';

interface Props {
  runId: number;
  /**
   * Applies placement operations (move/swap/teacher/room/delete/lock) through
   * the conflict-gated manual editor - on a published timetable the viewer
   * opens a draft first. Resolves with the gate's verdict.
   */
  onApplyOps: (ops: EditOperation[], reason: string) => Promise<ApplyOutcome>;
}

const isEditorOp = (a: AgentProposedAction) => a.action_type === 'editor_op';

/**
 * Whole-timetable AI editing. Two kinds of proposals come back:
 *
 *  - PLACEMENT changes ("move DBMS to Thursday", "swap these two", "give it to
 *    Dr. Rao"): editor operations. The backend already pre-checked each one
 *    against the same conflict gate the manual editor uses, and applying goes
 *    through that gate again - instant, undoable, never a re-solve.
 *  - HOURS changes ("remove Cloud Computing", "one more class a week"):
 *    subject overrides that fork a new run and re-solve it through the real
 *    solver (POST .../ai-apply), so they are feasibility-checked like any
 *    other generation.
 *
 * The model only ever PROPOSES; nothing is written until the admin reviews
 * the list and applies it.
 */
export function TimetableAIAssistant({ runId, onApplyOps }: Props) {
  const navigate = useNavigate();
  const [instruction, setInstruction] = useState('');
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState<'ops' | 'regen' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [conflicts, setConflicts] = useState<EditConflict[]>([]);
  const [done, setDone] = useState<string | null>(null);
  const [summary, setSummary] = useState<string | null>(null);
  const [actions, setActions] = useState<AgentProposedAction[]>([]);

  const placement = actions.filter(isEditorOp);
  const regen = actions.filter((a) => !isEditorOp(a));

  const runPlan = async () => {
    if (!instruction.trim()) return;
    setLoading(true);
    setError(null);
    setConflicts([]);
    setDone(null);
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

  const removeAction = (action: AgentProposedAction) => setActions(actions.filter((a) => a !== action));

  const applyPlacement = async () => {
    setApplying('ops');
    setError(null);
    setConflicts([]);
    const out = await onApplyOps(
      placement.map((a) => a.payload as EditOperation),
      `AI assistant: ${placement.map((a) => a.description).join('; ')}`,
    );
    setApplying(null);
    if (out.ok) {
      setDone(`${placement.length} change${placement.length === 1 ? '' : 's'} applied. Use Undo to reverse them.`);
      setActions(regen);
    } else if (out.violations.length) {
      setConflicts(out.violations);
    } else {
      setError(out.error || 'Failed to apply the changes.');
    }
  };

  const applyRegenerate = async () => {
    if (regen.length === 0) return;
    setApplying('regen');
    setError(null);
    try {
      const response = await timetableApi.aiApply(runId, regen);
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
            setApplying(null);
            setError(updated.data.llm_explanation || 'Regenerating the timetable with these changes failed.');
          }
        } catch {
          clearInterval(pollInterval);
          setApplying(null);
          setError("Failed to check the new version's status.");
        }
      }, 2000);
    } catch (err: any) {
      setApplying(null);
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
        Prefer typing to clicking? Say what you want - "Move Data Structures for Section A to Thursday afternoon",
        "Swap these two classes", "Give DBMS to Dr. Rao", "Remove Cloud Computing", "One more Maths class a week".
        It only proposes; you review, then apply. Placement changes are checked against every rule and applied
        instantly (with Undo). Hours changes regenerate the timetable as a new version through the solver.
        Everything the assistant can do you can also do by hand with "Edit timetable".
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
      {conflicts.length > 0 && (
        <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          <p className="font-medium">These changes would create conflicts, so none were applied:</p>
          <ul className="mt-1 list-disc pl-5">{conflicts.map((c, i) => <li key={i}>{c.message}</li>)}</ul>
        </div>
      )}
      {done && (
        <div className="mt-3 flex items-center gap-2 rounded-lg border border-green-200 bg-green-50 p-3 text-sm text-green-800">
          <Check size={16} /> {done}
        </div>
      )}

      {summary && (
        <div className="mt-4 rounded-lg border border-purple-200 bg-white p-3">
          <p className="text-sm text-gray-700 whitespace-pre-wrap">{summary}</p>
        </div>
      )}

      {[
        { title: 'Placement changes - applied instantly, undoable', items: placement, apply: applyPlacement, key: 'ops' as const, label: `Apply ${placement.length} placement change${placement.length === 1 ? '' : 's'}` },
        { title: 'Hours changes - regenerate the timetable as a new version', items: regen, apply: applyRegenerate, key: 'regen' as const, label: `Apply ${regen.length} change${regen.length === 1 ? '' : 's'} and regenerate` },
      ].filter((group) => group.items.length > 0).map((group) => (
        <div key={group.key} className="mt-3 space-y-2">
          <p className="text-sm font-medium text-purple-900">{group.title} - review before applying:</p>
          {group.items.map((action, index) => (
            <div key={index} className="flex items-center justify-between rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm">
              <span className="text-gray-800">{action.description}</span>
              <button onClick={() => removeAction(action)} className="p-1 text-red-500 hover:bg-red-50 rounded" title="Remove this change">
                <Trash2 size={16} />
              </button>
            </div>
          ))}
          <button
            onClick={group.apply} disabled={applying !== null}
            className="mt-2 flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
          >
            {applying === group.key && <RefreshCw size={16} className="animate-spin" />}
            {applying === group.key ? (group.key === 'regen' ? 'Regenerating timetable...' : 'Applying...') : group.label}
          </button>
        </div>
      ))}
    </div>
  );
}
