import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, Link, useNavigate, useLocation } from 'react-router-dom';
import {
  timetableApi, timetableEditorApi, firstYearImportApi, sectionsApi, subjectsApi, teachersApi, roomsApi, constraintsApi, subjectTypesApi, yearsApi,
} from '../api/client';
import {
  TimetableEntry, Section, Subject, Teacher, Room, TimetableRun, AcademicYear, EditOperation, SlotStatus, FirstYearTile,
} from '../types';
import {
  ChevronLeft, Download, Users, BookOpen, MapPin, SlidersHorizontal, Star, History, GitBranch, AlertTriangle, ChevronDown,
  ChevronUp, CheckCircle2, Pencil, Undo2, Redo2, ListChecks, UserX, X,
} from 'lucide-react';
import { TimetableAIAssistant } from '../components/TimetableAIAssistant';
import { CustomFilterView } from '../components/CustomFilterView';
import { TimetableGrid, ViewMode } from '../components/timetable/TimetableGrid';
import { EntryEditorPanel } from '../components/timetable/EntryEditorPanel';
import { AddEntryPanel, AddDraft } from '../components/timetable/AddEntryPanel';
import { HistoryPanel } from '../components/timetable/HistoryPanel';
import { HoursTracker } from '../components/timetable/HoursTracker';
import { BulkBar } from '../components/timetable/BulkBar';
import { SubstitutePanel } from '../components/timetable/SubstitutePanel';
import { useTimetableEditor, conflictsFromError, ApplyOutcome } from '../hooks/useTimetableEditor';
import { useAuth } from '../context/AuthContext';
import { DEFAULT_SLOTS, ScheduleSlot } from '../utils/schedule';
import { sectionLabel } from '../utils/sectionLabel';
import { TIMEZONE, formatInTimezone } from '../hooks/timezone';
import { canManageTimetables } from '../auth/roles';

const groupOf = (e: TimetableEntry) => e.session_group || `row:${e.id}`;

export function TimetableViewer() {
  const { runId } = useParams<{ runId: string }>();
  const id = parseInt(runId!, 10);
  const timezone = TIMEZONE;
  const { user } = useAuth();
  const canEdit = canManageTimetables(user?.role);
  const navigate = useNavigate();
  const location = useLocation();

  const [entries, setEntries] = useState<TimetableEntry[]>([]);
  const [run, setRun] = useState<TimetableRun | null>(null);
  const [sections, setSections] = useState<Record<string, Section>>({});
  const [years, setYears] = useState<Record<string, AcademicYear>>({});
  const [subjects, setSubjects] = useState<Record<string, Subject>>({});
  const [subjectTypeColors, setSubjectTypeColors] = useState<Record<string, string>>({});
  const [teachers, setTeachers] = useState<Record<string, Teacher>>({});
  // Central first-year classes that book this department's teachers/rooms; drawn read-only in the teacher/room views.
  const [firstYearTiles, setFirstYearTiles] = useState<FirstYearTile[]>([]);
  const [rooms, setRooms] = useState<Record<string, Room>>({});
  const [batchToSection, setBatchToSection] = useState<Record<string, string>>({});
  const [sectionSubjects, setSectionSubjects] = useState<Record<string, string[]>>({});
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState<ViewMode>('section');
  const [showCustom, setShowCustom] = useState(false);
  const [selectedEntity, setSelectedEntity] = useState<string>('');
  const [publishing, setPublishing] = useState(false);
  const [alternatives, setAlternatives] = useState<any[]>([]);
  const [selectedAlternative, setSelectedAlternative] = useState(1);
  const [validation, setValidation] = useState<{ valid: boolean; issues?: Array<{ type?: string; message: string }> } | null>(null);
  const [usingAlternative, setUsingAlternative] = useState(false);
  const [scheduleSlots, setScheduleSlots] = useState<ScheduleSlot[]>(DEFAULT_SLOTS);
  const [warningsExpanded, setWarningsExpanded] = useState(false);
  const [issuesExpanded, setIssuesExpanded] = useState(false);

  // ---- manual editing state ----
  const [editMode, setEditMode] = useState(false);
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null);
  const [adding, setAdding] = useState<AddDraft | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const [showSubstitute, setShowSubstitute] = useState(false);
  const [multiSelected, setMultiSelected] = useState<Set<string>>(new Set());
  const [changedGroups, setChangedGroups] = useState<Set<string>>(new Set());
  const [dragging, setDragging] = useState<TimetableEntry | null>(null);
  const dragRef = useRef<TimetableEntry | null>(null);
  const [dragStatus, setDragStatus] = useState<Record<string, SlotStatus> | null>(null);
  const [dragLoading, setDragLoading] = useState(false);
  const [notice, setNotice] = useState<{ message: string; kind: 'ok' | 'error' } | null>(null);

  const warnings: string[] = run?.solver_output?.warnings || [];
  const isDraft = !!run && !run.is_published && run.status === 'completed';
  const editing = canEdit && editMode && isDraft;

  const say = useCallback((message: string, kind: 'ok' | 'error') => setNotice({ message, kind }), []);
  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(null), notice.kind === 'error' ? 9000 : 4000);
    return () => clearTimeout(t);
  }, [notice]);

  const loadChanges = async (parentRunId: number | null | undefined) => {
    if (!parentRunId) { setChangedGroups(new Set()); return; }
    try {
      const diff = await timetableApi.compare(parentRunId, id);
      setChangedGroups(new Set<string>(diff.data.changes.map((c: { session_group: string }) => c.session_group)));
    } catch {
      setChangedGroups(new Set());
    }
  };

  // Everything that can change after an edit; leaves selections alone.
  const reloadEntries = useCallback(async () => {
    const [entriesRes, runRes, validationRes] = await Promise.all([
      timetableApi.getEntries(id), timetableApi.getRun(id), timetableApi.validate(id),
    ]);
    setEntries(entriesRes.data);
    setRun(runRes.data);
    setValidation(validationRes.data);
    await loadChanges(runRes.data.parent_run_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const editor = useTimetableEditor(id, editing, reloadEntries);

  useEffect(() => {
    setEditMode(!!(location.state as { edit?: boolean } | null)?.edit);
    setSelectedGroup(null);
    setAdding(null);
    setShowHistory(false);
    setShowSubstitute(false);
    setMultiSelected(new Set());
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  const fetchData = async () => {
    try {
      const [entriesRes, runRes, sectionsRes, subjectsRes, teachersRes, roomsRes, alternativesRes, validationRes, slotsRes, subjectTypesRes, yearsRes, sectionSubjectsRes] = await Promise.all([
        timetableApi.getEntries(id),
        timetableApi.getRun(id),
        sectionsApi.list(),
        subjectsApi.list(),
        teachersApi.list(),
        roomsApi.list(),
        timetableApi.getAlternatives(id),
        timetableApi.validate(id),
        constraintsApi.listTimeSlots(),
        subjectTypesApi.list(),
        yearsApi.list(),
        constraintsApi.getAllSectionSubjects(),
      ]);

      const yearMap: Record<string, AcademicYear> = {};
      yearsRes.data.forEach((y: AcademicYear) => { yearMap[y.id] = y; });
      setYears(yearMap);

      const colorMap: Record<string, string> = {};
      subjectTypesRes.data.forEach((t: { id: string; colour_hex: string }) => { colorMap[t.id] = t.colour_hex; });
      setSubjectTypeColors(colorMap);

      setEntries(entriesRes.data);
      setRun(runRes.data);
      setAlternatives(alternativesRes.data.alternatives || []);
      setSelectedAlternative(1);
      setValidation(validationRes.data);
      setScheduleSlots(slotsRes.data.length ? slotsRes.data : DEFAULT_SLOTS);

      const secMap: Record<string, Section> = {};
      sectionsRes.data.forEach((s: Section) => { secMap[s.id] = s; });
      setSections(secMap);

      const subjMap: Record<string, Subject> = {};
      subjectsRes.data.forEach((s: Subject) => { subjMap[s.id] = s; });
      setSubjects(subjMap);

      const teachMap: Record<string, Teacher> = {};
      teachersRes.data.forEach((t: Teacher) => { teachMap[t.id] = t; });
      setTeachers(teachMap);

      const roomMap: Record<string, Room> = {};
      roomsRes.data.forEach((r: Room) => { roomMap[r.id] = r; });
      setRooms(roomMap);

      const ssMap: Record<string, string[]> = {};
      sectionSubjectsRes.data.forEach((row: { section_id: string; subject_id: string }) => {
        (ssMap[row.section_id] ||= []).push(row.subject_id);
      });
      setSectionSubjects(ssMap);

      const allBatchesRes = await constraintsApi.getAllLabBatches();
      const batchMap: Record<string, string> = {};
      allBatchesRes.data.forEach((batch: { id: string; section_id: string }) => {
        batchMap[batch.id] = batch.section_id;
      });
      setBatchToSection(batchMap);

      const firstSection = Object.keys(secMap)[0];
      if (firstSection) setSelectedEntity(firstSection);

      // Optional extra: a failure here must never stop the timetable from loading.
      if (runRes.data.department_id) {
        firstYearImportApi.tiles(runRes.data.department_id)
          .then((res) => setFirstYearTiles(res.data))
          .catch(() => setFirstYearTiles([]));
      } else {
        setFirstYearTiles([]);
      }

      await loadChanges(runRes.data.parent_run_id);
    } catch (error) {
      console.error('Failed to fetch data:', error);
    } finally {
      setLoading(false);
    }
  };

  const batchesBySection: Record<string, string[]> = {};
  Object.entries(batchToSection).forEach(([batch, section]) => { (batchesBySection[section] ||= []).push(batch); });

  const handleAlternativeChange = async (rank: number) => {
    setSelectedAlternative(rank);
    try {
      if (rank === 1) {
        const response = await timetableApi.getEntries(id);
        setEntries(response.data);
      } else {
        const response = await timetableApi.getAlternative(id, rank);
        setEntries(response.data.entries || []);
      }
    } catch (error) {
      console.error('Failed to load timetable alternative:', error);
    }
  };

  const handleUseAlternative = async () => {
    setUsingAlternative(true);
    try {
      const response = await timetableApi.useAlternative(id, selectedAlternative);
      navigate(`/runs/${response.data.id}`);
    } catch (error) {
      console.error('Failed to use timetable alternative:', error);
    } finally {
      setUsingAlternative(false);
    }
  };

  const getSubjectName = (subjectId: string) => subjects[subjectId]?.name || subjectId;
  const getTeacherName = (teacherId: string) => (teacherId ? teachers[teacherId]?.name || teacherId : '');
  const getRoomName = (roomId: string) => (roomId ? rooms[roomId]?.name || roomId : '');
  const sectionOf = (entry: TimetableEntry) => entry.section_id || (entry.batch_id ? batchToSection[entry.batch_id] : undefined);
  const audienceLabel = (entry: TimetableEntry) => {
    const name = sections[sectionOf(entry) || '']?.name || sectionOf(entry) || '';
    return entry.batch_id ? `${name} · ${entry.batch_id}` : name;
  };

  // Colours come from the subject_types catalog (Phase 2.1).
  const colorStyle = (subjectId: string): React.CSSProperties => {
    const hex = subjectTypeColors[subjects[subjectId]?.type || ''] || 'E5E7EB';
    return { backgroundColor: `#${hex}`, borderColor: `#${hex}` };
  };

  // A per-day lunch band, only meaningful in the section view.
  const currentLunchWindows: Record<string, [string, string]> = (() => {
    if (viewMode !== 'section') return {};
    const section = sections[selectedEntity];
    const year = section ? years[section.year_id] : undefined;
    return year?.lunch_windows || {};
  })();

  const getEntriesForEntity = (entityId: string) =>
    entries.filter((entry) => {
      if (viewMode === 'section') {
        return entry.section_id === entityId || entry.batch_id === entityId
          || (!!entry.batch_id && batchToSection[entry.batch_id] === entityId);
      }
      return viewMode === 'teacher' ? entry.teacher_id === entityId : entry.room_id === entityId;
    });

  const entityOptions = viewMode === 'section'
    ? Object.values(sections).map((s) => ({ value: s.id, label: sectionLabel(s, years) }))
    : viewMode === 'teacher'
      ? Object.values(teachers).map((t) => ({ value: t.id, label: t.name }))
      : Object.values(rooms).map((r) => ({ value: r.id, label: r.name }));

  const changeViewMode = (mode: ViewMode) => {
    setShowCustom(false);
    setViewMode(mode);
    setSelectedGroup(null);
    setAdding(null);
    const first = mode === 'section' ? Object.keys(sections)[0] : mode === 'teacher' ? Object.keys(teachers)[0] : Object.keys(rooms)[0];
    setSelectedEntity(first || '');
  };

  // ---- exports / publish ----
  const downloadBlob = (data: BlobPart, filename: string) => {
    const url = window.URL.createObjectURL(new Blob([data]));
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.URL.revokeObjectURL(url);
  };

  const handleExport = async (format: string) => {
    try {
      const response = await timetableApi.export(id, format, viewMode, selectedEntity || undefined);
      downloadBlob(response.data, `timetable_run_${runId}.${format}`);
    } catch (error) {
      console.error('Export failed:', error);
    }
  };

  const currentYearId = !showCustom && viewMode === 'section' ? sections[selectedEntity]?.year_id : undefined;
  const handleExportYear = async () => {
    if (!currentYearId) return;
    try {
      const response = await timetableApi.export(id, 'xlsx', 'section', undefined, currentYearId);
      downloadBlob(response.data, `timetable_${currentYearId}.xlsx`);
    } catch (error) {
      console.error('Year export failed:', error);
    }
  };

  const handlePublish = async () => {
    setPublishing(true);
    try {
      await timetableApi.publish(id);
      await fetchData();
      say('Timetable published.', 'ok');
    } catch (err) {
      const { violations, error } = conflictsFromError(err);
      say(violations.length ? `Can't publish - ${violations[0].message}${violations.length > 1 ? ` (+${violations.length - 1} more)` : ''}` : (error || 'Publish failed.'), 'error');
    } finally {
      setPublishing(false);
    }
  };

  // ---- editing ----
  const startEditing = async () => {
    if (!run) return;
    if (!run.is_published) { setEditMode(true); return; }
    try {
      const res = await timetableEditorApi.openDraft(id);
      say(res.data.created ? `Draft #${res.data.run.id} created from the published timetable.` : `Continuing draft #${res.data.run.id}.`, 'ok');
      navigate(`/runs/${res.data.run.id}`, { state: { edit: true } });
    } catch (err) {
      say(conflictsFromError(err).error || 'Could not open a draft.', 'error');
    }
  };

  // Used by the AI assistant: a published timetable gets a draft first.
  const applyOpsViaDraft = async (ops: EditOperation[], reason: string): Promise<ApplyOutcome> => {
    if (!run?.is_published) return editor.apply(ops, reason);
    try {
      const draft = await timetableEditorApi.openDraft(id);
      await timetableEditorApi.apply(draft.data.run.id, ops, reason);
      navigate(`/runs/${draft.data.run.id}`, { state: { edit: true } });
      return { ok: true, violations: [] };
    } catch (err) {
      return { ok: false, ...conflictsFromError(err) };
    }
  };

  const outcomeNotice = (out: ApplyOutcome, ok: string) => {
    if (out.ok) say(ok, 'ok');
    else say(out.violations.length ? out.violations.map((v) => v.message).join(' ') : (out.error || 'Nothing was changed.'), 'error');
  };

  const handleUndo = async () => outcomeNotice(await editor.undo(), 'Undone.');
  const handleRedo = async () => outcomeNotice(await editor.redo(), 'Redone.');

  useEffect(() => {
    if (!editing) return;
    const onKey = (ev: KeyboardEvent) => {
      const tag = (ev.target as HTMLElement | null)?.tagName;
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
      if (!(ev.ctrlKey || ev.metaKey)) return;
      const key = ev.key.toLowerCase();
      if (key === 'z' && !ev.shiftKey && editor.canUndo) { ev.preventDefault(); handleUndo(); }
      else if ((key === 'y' || (key === 'z' && ev.shiftKey)) && editor.canRedo) { ev.preventDefault(); handleRedo(); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing, editor.canUndo, editor.canRedo]);

  const clearDrag = () => {
    dragRef.current = null;
    setDragging(null);
    setDragStatus(null);
    setDragLoading(false);
  };

  const handleDragStart = async (entry: TimetableEntry) => {
    dragRef.current = entry;
    setDragging(entry);
    setDragStatus(null);
    setDragLoading(true);
    try {
      const res = await timetableEditorApi.slotMap(id, groupOf(entry), viewMode, selectedEntity);
      if (dragRef.current !== entry) return; // dropped/cancelled while loading
      const map: Record<string, SlotStatus> = {};
      res.data.slots.forEach((s: SlotStatus) => { map[`${s.day}-${s.period}`] = s; });
      setDragStatus(map);
    } catch {
      if (dragRef.current === entry) say('Could not check free slots.', 'error');
    } finally {
      if (dragRef.current === entry) setDragLoading(false);
    }
  };

  const handleDrop = async (day: string, period: number) => {
    const entry = dragRef.current;
    if (!entry) return;
    const status = dragStatus?.[`${day}-${period}`];
    if (!status) { say('Still checking which slots are free - try again in a moment.', 'error'); return; }
    let op: EditOperation;
    let okText: string;
    if (status.ok) {
      if (day === entry.day && period === entry.period) { clearDrag(); return; }
      op = { type: 'move', session_group: groupOf(entry), day, period };
      okText = 'Class moved.';
    } else if (status.occupant_group && status.swap_ok) {
      op = { type: 'swap', session_group_a: groupOf(entry), session_group_b: status.occupant_group };
      okText = 'Classes swapped.';
    } else {
      const reasons = status.occupant_group && status.swap_reasons.length ? status.swap_reasons : status.reasons;
      say(`Can't drop here: ${reasons.join(' ')}`, 'error');
      clearDrag();
      return;
    }
    clearDrag();
    outcomeNotice(await editor.apply([op]), okText);
  };

  const onCardClick = (entry: TimetableEntry, ev: React.MouseEvent) => {
    if (!canEdit) return;
    setAdding(null);
    setShowHistory(false);
    setShowSubstitute(false);
    // Shift+click (or any click while a selection exists) builds a bulk selection.
    if (editing && (ev.shiftKey || multiSelected.size > 0)) {
      const g = groupOf(entry);
      setSelectedGroup(null);
      setMultiSelected((cur) => {
        const next = new Set(cur);
        if (next.has(g)) next.delete(g); else next.add(g);
        return next;
      });
      return;
    }
    setSelectedGroup(groupOf(entry));
  };

  const applyBulk = async (build: (group: string) => EditOperation, ok: string) => {
    const ops = [...multiSelected].map(build);
    const out = await editor.apply(ops, `Bulk edit of ${ops.length} class${ops.length === 1 ? '' : 'es'}`);
    outcomeNotice(out, ok);
    if (out.ok) setMultiSelected(new Set());
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  const entityEntries = getEntriesForEntity(selectedEntity);
  const selectedEntry = selectedGroup ? entries.find((e) => groupOf(e) === selectedGroup) : undefined;
  const publishBlocked = !!validation && !validation.valid;
  const firstSlot = scheduleSlots[0];
  const teacher = viewMode === 'teacher' ? teachers[selectedEntity] : undefined;
  const dayLoad = teacher
    ? Object.entries(entityEntries.reduce<Record<string, number>>((acc, e) => { acc[e.day] = (acc[e.day] || 0) + 1; return acc; }, {}))
    : [];

  const modeButton = (active: boolean) =>
    `flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${active ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`;

  return (
    <div className="max-w-7xl mx-auto">
      {notice && (
        <div role="status" className={`fixed right-4 top-4 z-50 flex max-w-md items-start gap-2 rounded-lg border px-4 py-3 text-sm shadow-lg ${notice.kind === 'error' ? 'border-red-200 bg-red-50 text-red-800' : 'border-green-200 bg-green-50 text-green-800'}`}>
          <span className="flex-1">{notice.message}</span>
          <button onClick={() => setNotice(null)} aria-label="Dismiss"><X size={14} /></button>
        </div>
      )}

      <div className="flex flex-wrap justify-between items-center gap-3 mb-6">
        <div className="flex items-center gap-4">
          <Link to="/runs" className="text-gray-600 hover:text-gray-900">
            <ChevronLeft size={20} />
          </Link>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            {run ? `Timetable — ${formatInTimezone(run.created_at, timezone)}` : `Timetable #${runId}`}
            <span className="text-sm font-normal text-gray-400">#{runId}</span>
            {run?.is_published && (
              <span className="flex items-center gap-1 text-xs font-medium text-green-700 bg-green-100 px-2 py-0.5 rounded-full">
                <Star size={12} /> Published
              </span>
            )}
            {run && !run.is_published && run.parent_run_id && (
              <span className="text-xs font-medium text-fuchsia-700 bg-fuchsia-100 px-2 py-0.5 rounded-full">Draft</span>
            )}
          </h1>
        </div>
        <div className="flex flex-wrap gap-2">
          {canEdit && run?.status === 'completed' && (
            editing ? (
              <>
                <button onClick={handleUndo} disabled={!editor.canUndo || editor.busy} title="Undo (Ctrl+Z)"
                  className="flex items-center gap-1.5 px-3 py-2 border border-gray-300 rounded-lg text-sm hover:bg-gray-50 disabled:opacity-40">
                  <Undo2 size={16} /> Undo
                </button>
                <button onClick={handleRedo} disabled={!editor.canRedo || editor.busy} title="Redo (Ctrl+Y)"
                  className="flex items-center gap-1.5 px-3 py-2 border border-gray-300 rounded-lg text-sm hover:bg-gray-50 disabled:opacity-40">
                  <Redo2 size={16} /> Redo
                </button>
                <button onClick={() => { setSelectedGroup(null); setAdding(null); setShowSubstitute(true); }}
                  className="flex items-center gap-1.5 px-3 py-2 border border-gray-300 rounded-lg text-sm hover:bg-gray-50">
                  <UserX size={16} /> Substitute teacher
                </button>
                <button onClick={() => { setSelectedGroup(null); setAdding(null); setShowSubstitute(false); setShowHistory(true); }}
                  className="flex items-center gap-1.5 px-3 py-2 border border-gray-300 rounded-lg text-sm hover:bg-gray-50">
                  <ListChecks size={16} /> Change log
                </button>
                <button onClick={() => { setEditMode(false); setSelectedGroup(null); setAdding(null); }}
                  className="flex items-center gap-1.5 px-3 py-2 border border-gray-300 rounded-lg text-sm hover:bg-gray-50">
                  Done editing
                </button>
              </>
            ) : (
              <button onClick={startEditing}
                className="flex items-center gap-2 px-4 py-2 bg-fuchsia-600 text-white rounded-lg hover:bg-fuchsia-700 transition-colors text-sm">
                <Pencil size={16} /> Edit timetable
              </button>
            )
          )}
          <Link
            to={`/runs/${runId}/versions`}
            className="flex items-center gap-2 px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors text-sm"
          >
            <History size={18} />
            Versions
          </Link>
          {run && !run.is_published && (
            <button
              onClick={handlePublish}
              disabled={publishing || publishBlocked}
              title={publishBlocked ? 'Resolve the clashes listed below before publishing.' : undefined}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors text-sm"
            >
              <Star size={18} />
              {publishing ? 'Publishing...' : 'Publish'}
            </button>
          )}
          {!showCustom && (<>
            <button onClick={() => handleExport('xlsx')} className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors">
              <Download size={20} />
              Export Excel
            </button>
            <button onClick={() => handleExport('pdf')} className="flex items-center gap-2 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors">
              <Download size={20} />
              Export PDF
            </button>
          </>)}
          {currentYearId && (
            <button onClick={handleExportYear} title="One Excel workbook with a sheet for every section in this year"
              className="flex items-center gap-2 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors text-sm">
              <Download size={18} />
              Export whole year
            </button>
          )}
        </div>
      </div>

      {run && !run.is_published && !editing && (
        <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mb-4">
          This run isn't published yet - students and faculty won't see it under "My Timetable" until you publish it.
        </p>
      )}

      {editing && (
        <p className="text-sm text-fuchsia-900 bg-fuchsia-50 border border-fuchsia-200 rounded-lg px-3 py-2 mb-4">
          <strong>Editing draft #{runId}.</strong> Drag a class to move it (green = free, amber = swap, red = blocked), click a class to change its
          teacher/room, lock or delete it, Shift+click several to edit them together, or click an empty slot to add one. Changes that would create a clash are refused. Classes with a
          magenta outline differ from the version this draft started from. Publish when you're done.
        </p>
      )}

      {run && canEdit && run.status === 'completed' && (
        <div className="mb-4">
          <TimetableAIAssistant runId={id} onApplyOps={applyOpsViaDraft} />
        </div>
      )}

      {warnings.length > 0 && (
        <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3">
          <button type="button" onClick={() => setWarningsExpanded((c) => !c)} className="flex w-full items-center justify-between text-sm font-medium text-amber-800">
            <span className="flex items-center gap-2">
              <AlertTriangle size={16} />
              {warnings.length} thing{warnings.length === 1 ? '' : 's'} were skipped
            </span>
            {warningsExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </button>
          {warningsExpanded && (
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-amber-800">
              {warnings.map((warning, index) => <li key={index}>{warning}</li>)}
            </ul>
          )}
        </div>
      )}

      {alternatives.length > 1 && (
        <div className="mb-5 flex flex-wrap items-center gap-3 rounded-lg border border-blue-100 bg-blue-50 p-3">
          <GitBranch size={20} className="text-blue-700" />
          <label htmlFor="alternative-select" className="text-sm font-medium text-blue-900">Alternative timetable</label>
          <select id="alternative-select" value={selectedAlternative} onChange={(e) => handleAlternativeChange(parseInt(e.target.value, 10))}
            className="px-3 py-1.5 border border-blue-200 rounded-lg bg-white text-sm text-gray-800">
            {alternatives.map((alternative) => (
              <option key={alternative.rank} value={alternative.rank}>
                Option {alternative.rank}{alternative.diversity_from_previous ? ` - ${alternative.diversity_from_previous} classes placed differently` : ''}
              </option>
            ))}
          </select>
          <button type="button" onClick={handleUseAlternative} disabled={usingAlternative}
            className="ml-auto rounded-lg bg-blue-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-800 disabled:opacity-50">
            {usingAlternative ? 'Creating version...' : 'Use this alternative'}
          </button>
        </div>
      )}

      {validation && (
        validation.valid ? (
          <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-green-200 bg-green-50 px-3 py-1 text-sm text-green-800">
            <CheckCircle2 size={14} /> No clashes
          </div>
        ) : (
          <div className="mb-5 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            <button type="button" onClick={() => setIssuesExpanded((c) => !c)} className="flex w-full items-center justify-between font-medium">
              <span>This timetable has {validation.issues?.length || 'some'} clash{validation.issues?.length === 1 ? '' : 'es'} - it can't be published until they are fixed</span>
              {issuesExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </button>
            {(issuesExpanded ? validation.issues : validation.issues?.slice(0, 3))?.map((issue, i) => (
              <p key={`${issue.message}-${i}`} className="mt-1">{issue.message}</p>
            ))}
          </div>
        )
      )}

      {/* View mode selector */}
      <div className="flex gap-2 mb-6">
        {([['section', Users, 'By Section'], ['teacher', BookOpen, 'By Teacher'], ['room', MapPin, 'By Room']] as const).map(([mode, Icon, label]) => (
          <button key={mode} onClick={() => changeViewMode(mode)} className={modeButton(!showCustom && viewMode === mode)}>
            <Icon size={20} />
            {label}
          </button>
        ))}
        <button onClick={() => { setShowCustom(true); setSelectedGroup(null); setAdding(null); }} className={modeButton(showCustom)}>
          <SlidersHorizontal size={20} />
          Custom Filter
        </button>
      </div>

      {showCustom ? (
        <CustomFilterView runId={id} />
      ) : (<>
        {/* Entity selector */}
        <div className="mb-6">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Select {viewMode === 'section' ? 'Section' : viewMode === 'teacher' ? 'Teacher' : 'Room'}
          </label>
          <select value={selectedEntity} onChange={(e) => { setSelectedEntity(e.target.value); setSelectedGroup(null); }}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent">
            {entityOptions.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
          </select>
        </div>

        {editing && multiSelected.size > 0 && (
          <BulkBar
            count={multiSelected.size}
            teachers={Object.values(teachers)}
            rooms={Object.values(rooms)}
            busy={editor.busy}
            onLock={() => applyBulk((g) => ({ type: 'lock', session_group: g }), 'Classes locked.')}
            onUnlock={() => applyBulk((g) => ({ type: 'unlock', session_group: g }), 'Classes unlocked.')}
            onDelete={() => { if (window.confirm(`Delete ${multiSelected.size} selected class(es)?`)) applyBulk((g) => ({ type: 'delete', session_group: g }), 'Classes deleted.'); }}
            onChangeTeacher={(teacherId) => applyBulk((g) => ({ type: 'change_teacher', session_group: g, teacher_id: teacherId, scope: 'all_sessions' }), 'Teacher changed.')}
            onChangeRoom={(roomId) => applyBulk((g) => ({ type: 'change_room', session_group: g, room_id: roomId }), 'Room changed.')}
            onClear={() => setMultiSelected(new Set())}
          />
        )}

        {editing && viewMode === 'section' && selectedEntity && (
          <HoursTracker
            sectionId={selectedEntity}
            subjectIds={sectionSubjects[selectedEntity] || []}
            subjects={subjects}
            entries={entityEntries}
            canAdd
            onAdd={(subjectId) => { setSelectedGroup(null); setAdding({ day: firstSlot.day, period: firstSlot.period_index, sectionId: selectedEntity, subjectId }); }}
          />
        )}

        {teacher && (
          <div className="mb-4 flex flex-wrap items-center gap-2 text-xs">
            <span className={`rounded-full border px-2.5 py-1 ${entityEntries.length > teacher.max_weekly_hours ? 'border-red-300 bg-red-50 text-red-800' : 'border-gray-200 bg-white text-gray-700'}`}>
              Week: {entityEntries.length}/{teacher.max_weekly_hours} periods
            </span>
            {dayLoad.map(([day, count]) => (
              <span key={day} className={`rounded-full border px-2.5 py-1 ${count > teacher.max_daily_classes ? 'border-red-300 bg-red-50 text-red-800' : 'border-gray-200 bg-white text-gray-700'}`}>
                {day}: {count}/{teacher.max_daily_classes}
              </span>
            ))}
          </div>
        )}

        <TimetableGrid
          viewMode={viewMode}
          entries={entityEntries}
          firstYearTiles={viewMode === 'section' ? [] : firstYearTiles.filter((t) => t.resource_type === viewMode && t.resource_id === selectedEntity)}
          slots={scheduleSlots}
          lunchWindows={currentLunchWindows}
          subjectName={getSubjectName}
          teacherName={getTeacherName}
          roomName={getRoomName}
          audienceLabel={audienceLabel}
          colorStyle={colorStyle}
          editable={editing}
          selectedGroup={selectedGroup}
          multiSelected={multiSelected}
          changedGroups={changedGroups}
          dragStatus={dragStatus}
          dragging={dragging}
          dragLoading={dragLoading}
          onCardClick={onCardClick}
          onEmptyClick={(day, period) => { setSelectedGroup(null); setAdding({ day, period, sectionId: viewMode === 'section' ? selectedEntity : undefined }); }}
          onDragStart={handleDragStart}
          onDragEnd={clearDrag}
          onDrop={handleDrop}
        />

        {/* Legend */}
        <div className="mt-6 flex flex-wrap gap-4 text-sm text-gray-600">
          {Object.entries(subjectTypeColors).map(([type, hex]) => (
            <div key={type} className="flex items-center gap-2">
              <div className="w-4 h-4 rounded border" style={{ backgroundColor: `#${hex}`, borderColor: `#${hex}` }}></div>
              <span className="capitalize">{type}</span>
            </div>
          ))}
          {editing && (
            <>
              <span className="flex items-center gap-1"><Pencil size={12} /> edited by hand</span>
              <span className="flex items-center gap-1"><span className="inline-block h-3 w-3 rounded outline outline-2 outline-fuchsia-500" /> changed from previous version</span>
            </>
          )}
        </div>

        {canEdit && !editing && run?.status === 'completed' && (
          <p className="text-xs text-gray-400 mt-4">
            {run.is_published ? 'Click "Edit timetable" to make changes in a draft.' : 'Click "Edit timetable" to drag classes around, change teachers/rooms, or add and delete classes.'}
          </p>
        )}
      </>)}

      {showSubstitute && editing && (
        <SubstitutePanel
          runId={id}
          entries={entries}
          teachers={teachers}
          initialTeacherId={viewMode === 'teacher' ? selectedEntity : undefined}
          subjectName={getSubjectName}
          audienceLabel={audienceLabel}
          editor={editor}
          onClose={() => setShowSubstitute(false)}
          onNotice={say}
        />
      )}

      {showHistory && <HistoryPanel items={editor.history} onClose={() => setShowHistory(false)} />}

      {selectedEntry && !showCustom && (
        <EntryEditorPanel
          key={selectedGroup!}
          runId={id}
          entry={selectedEntry}
          blockLength={entries.filter((e) => groupOf(e) === selectedGroup).length}
          subjectName={getSubjectName(selectedEntry.subject_id)}
          audience={audienceLabel(selectedEntry)}
          slots={scheduleSlots}
          editor={editor}
          editable={editing}
          onClose={() => setSelectedGroup(null)}
          onNotice={say}
        />
      )}

      {adding && editing && !showCustom && (
        <AddEntryPanel
          initial={adding}
          sections={Object.values(sections)}
          years={years}
          subjects={subjects}
          sectionSubjects={sectionSubjects}
          batchesBySection={batchesBySection}
          teachers={Object.values(teachers)}
          rooms={Object.values(rooms)}
          slots={scheduleSlots}
          editor={editor}
          onClose={() => setAdding(null)}
          onNotice={say}
        />
      )}
    </div>
  );
}
