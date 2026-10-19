import { useCallback, useEffect, useState } from 'react';
import { timetableEditorApi } from '../api/client';
import { EditCheckResult, EditConflict, EditHistoryItem, EditOperation } from '../types';

export interface ApplyOutcome {
  ok: boolean;
  /** Conflicts that caused the change to be refused (HTTP 409). */
  violations: EditConflict[];
  /** A plain-language failure that isn't a scheduling conflict. */
  error?: string;
}

/** Pulls {type, message} conflicts out of an axios error, whichever shape the API used. */
export function conflictsFromError(err: any): { violations: EditConflict[]; error?: string } {
  const detail = err?.response?.data?.detail;
  if (detail && typeof detail === 'object' && Array.isArray(detail.violations)) {
    return { violations: detail.violations };
  }
  if (typeof detail === 'string') return { violations: [], error: detail };
  return { violations: [], error: 'Something went wrong. Nothing was changed.' };
}

/**
 * State + actions for editing one (draft) timetable run. Every mutation is
 * conflict-gated on the server, so `apply` resolves to {ok:false, violations}
 * instead of ever leaving the timetable in a clashing state.
 */
export function useTimetableEditor(runId: number, enabled: boolean, reload: () => Promise<void>) {
  const [busy, setBusy] = useState(false);
  const [canUndo, setCanUndo] = useState(false);
  const [canRedo, setCanRedo] = useState(false);
  const [history, setHistory] = useState<EditHistoryItem[]>([]);

  const refreshHistory = useCallback(async () => {
    if (!enabled) return;
    try {
      const res = await timetableEditorApi.history(runId);
      setHistory(res.data.items);
      setCanUndo(res.data.can_undo);
      setCanRedo(res.data.can_redo);
    } catch {
      /* history is informational - never block editing on it */
    }
  }, [runId, enabled]);

  useEffect(() => {
    refreshHistory();
  }, [refreshHistory]);

  const run = useCallback(
    async (call: () => Promise<unknown>): Promise<ApplyOutcome> => {
      setBusy(true);
      try {
        await call();
        await reload();
        await refreshHistory();
        return { ok: true, violations: [] };
      } catch (err) {
        return { ok: false, ...conflictsFromError(err) };
      } finally {
        setBusy(false);
      }
    },
    [reload, refreshHistory],
  );

  const apply = useCallback(
    (operations: EditOperation[], reason?: string) => run(() => timetableEditorApi.apply(runId, operations, reason)),
    [run, runId],
  );
  const undo = useCallback(() => run(() => timetableEditorApi.undo(runId)), [run, runId]);
  const redo = useCallback(() => run(() => timetableEditorApi.redo(runId)), [run, runId]);

  /** Dry-run: would these operations be accepted? Never changes anything. */
  const check = useCallback(
    async (operations: EditOperation[]): Promise<EditCheckResult> => {
      try {
        const res = await timetableEditorApi.check(runId, operations);
        return res.data;
      } catch (err) {
        const { violations, error } = conflictsFromError(err);
        return { ok: false, violations: violations.length ? violations : [{ type: 'ERROR', message: error || 'Check failed.' }], changed_groups: [] };
      }
    },
    [runId],
  );

  return { busy, canUndo, canRedo, history, apply, undo, redo, check, refreshHistory };
}
