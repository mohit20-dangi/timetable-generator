import { CSSProperties } from 'react';
import { Lock, Pencil, Plus } from 'lucide-react';
import { FirstYearTile, SlotStatus, TimetableEntry } from '../../types';
import { DAYS, DAY_LABELS, ScheduleSlot, timeLabel } from '../../utils/schedule';

export type ViewMode = 'section' | 'teacher' | 'room';

interface Props {
  viewMode: ViewMode;
  entries: TimetableEntry[];
  /** Centrally-allotted first-year classes of the selected teacher/room, drawn
   * read-only in the slots they block. Empty in the section view. */
  firstYearTiles?: FirstYearTile[];
  slots: ScheduleSlot[];
  lunchWindows: Record<string, [string, string]>;
  subjectName: (id: string) => string;
  teacherName: (id: string) => string;
  roomName: (id: string) => string;
  /** Which section(s) an entry is for - shown on the card in teacher/room views. */
  audienceLabel: (entry: TimetableEntry) => string;
  colorStyle: (subjectId: string) => CSSProperties;
  editable: boolean;
  selectedGroup: string | null;
  /** Classes picked with Shift+click for a bulk edit. */
  multiSelected: Set<string>;
  /** Blocks that differ from the run this draft was forked from. */
  changedGroups: Set<string>;
  /** Filled while a drag is in flight: where the dragged block may go. */
  dragStatus: Record<string, SlotStatus> | null;
  dragging: TimetableEntry | null;
  dragLoading: boolean;
  onCardClick: (entry: TimetableEntry, ev: React.MouseEvent) => void;
  onEmptyClick: (day: string, period: number) => void;
  onDragStart: (entry: TimetableEntry) => void;
  onDragEnd: () => void;
  onDrop: (day: string, period: number) => void;
}

const groupOf = (e: TimetableEntry) => e.session_group || `row:${e.id}`;

export function TimetableGrid(props: Props) {
  const { slots, entries, viewMode, editable, dragging, dragStatus } = props;
  const firstYearTiles = props.firstYearTiles ?? [];
  const periods = [...new Set(slots.map((s) => s.period_index))].sort((a, b) => a - b);
  const slotMap = new Map(slots.map((s) => [`${s.day}-${s.period_index}`, s]));

  // First period of each block: only that cell is draggable, so the drop
  // position always means "where the block STARTS".
  const blockStart = new Map<string, number>();
  entries.forEach((e) => {
    const g = groupOf(e);
    const cur = blockStart.get(`${g}|${e.day}`);
    if (cur === undefined || e.period < cur) blockStart.set(`${g}|${e.day}`, e.period);
  });
  const isStart = (e: TimetableEntry) => blockStart.get(`${groupOf(e)}|${e.day}`) === e.period;

  const isLunchSlot = (day: string, period: number): boolean => {
    const window = props.lunchWindows[day];
    const slot = slotMap.get(`${day}-${period}`);
    if (!window || !slot) return false;
    return slot.start_time.slice(0, 5) < window[1] && window[0] < slot.end_time.slice(0, 5);
  };

  const cellEntries = (day: string, period: number) => entries.filter((e) => e.day === day && e.period === period);
  const cellTiles = (day: string, period: number) =>
    firstYearTiles.filter((t) => t.day === day && t.periods.includes(period));

  /** A first-year class: fixed by the central timetable, so no drag, click or
   * edit - just the full tile, so a teacher's real week is visible. */
  const renderFirstYearTile = (tile: FirstYearTile, period: number) => {
    const first = period === tile.periods[0];
    const names = tile.faculty.map((f) => f.code).join(', ');
    const tip = tile.faculty.map((f) => (f.name ? `${f.code} - ${f.name}` : f.code)).join('\n');
    const title = 'First-year class from the central timetable - fixed, cannot be edited here.' + (tip ? `\n${tip}` : '');
    return (
      <div
        key={`fy-${tile.tile_id}-${tile.resource_id}-${period}`}
        className="relative p-2 rounded border border-dashed border-slate-400 bg-slate-100 text-xs text-gray-800"
        title={title}
      >
        <span className="absolute right-1 top-1 rounded bg-slate-600 px-1 text-[10px] leading-4 text-white">1st yr</span>
        <div className="font-medium pr-10">{tile.subject || '1st year class'}{!first && ' (cont.)'}</div>
        {first && (
          <>
            {tile.section && <div className="text-gray-700">{tile.section}{tile.batches.length > 0 && ` · ${tile.batches.join(', ')}`}</div>}
            {!tile.section && tile.batches.length > 0 && <div className="text-gray-600">Batch: {tile.batches.join(', ')}</div>}
            {names && <div className="text-gray-600">{names}</div>}
            {tile.room_text && <div className="text-gray-600">{tile.room_text}</div>}
          </>
        )}
      </div>
    );
  };

  const dropClass = (day: string, period: number): { cls: string; title?: string } => {
    if (!dragging || !dragStatus) return { cls: '' };
    const st = dragStatus[`${day}-${period}`];
    if (!st) return { cls: '' };
    if (st.ok) return { cls: 'bg-green-100 ring-2 ring-inset ring-green-400', title: 'Drop here to move' };
    if (st.occupant_group && st.swap_ok) return { cls: 'bg-amber-100 ring-2 ring-inset ring-amber-400', title: 'Drop here to swap places' };
    const reasons = st.occupant_group && st.swap_reasons.length ? st.swap_reasons : st.reasons;
    return { cls: 'bg-red-50 ring-1 ring-inset ring-red-300', title: `Not allowed: ${reasons.join(' ')}` };
  };

  const renderCard = (entry: TimetableEntry) => {
    const g = groupOf(entry);
    const start = isStart(entry);
    const selected = props.selectedGroup === g;
    const picked = props.multiSelected.has(g);
    const isDragged = dragging && groupOf(dragging) === g;
    return (
      <div
        key={entry.id}
        draggable={editable && start && !entry.is_locked}
        onDragStart={(ev) => {
          ev.dataTransfer.setData('text/plain', g);
          ev.dataTransfer.effectAllowed = 'move';
          props.onDragStart(entry);
        }}
        onDragEnd={props.onDragEnd}
        onClick={(ev) => props.onCardClick(entry, ev)}
        style={props.colorStyle(entry.subject_id)}
        className={[
          'relative p-2 rounded border text-xs text-gray-800 cursor-pointer hover:ring-2 hover:ring-blue-400',
          editable && start && !entry.is_locked ? 'active:cursor-grabbing' : '',
          selected ? 'ring-2 ring-blue-600' : '',
          picked ? 'ring-2 ring-blue-600 bg-blue-50' : '',
          isDragged ? 'opacity-40' : '',
          props.changedGroups.has(g) ? 'outline outline-2 outline-offset-1 outline-fuchsia-500' : '',
          start ? '' : 'opacity-80',
        ].join(' ')}
        title={editable ? (entry.is_locked ? 'Locked - click to edit or unlock' : 'Click to edit, drag to move') : undefined}
      >
        <div className="absolute right-1 top-1 flex gap-1 text-gray-600">
          {entry.is_manual && <Pencil size={11} aria-label="Edited by hand" />}
          {entry.is_locked && <Lock size={11} aria-label="Locked" />}
        </div>
        <div className="font-medium pr-6">{props.subjectName(entry.subject_id)}{!start && ' (cont.)'}</div>
        {viewMode !== 'section' && <div className="text-gray-700">{props.audienceLabel(entry)}</div>}
        {entry.batch_id && <div className="text-gray-600">Batch: {entry.batch_id}</div>}
        {!entry.teacher_id && !entry.room_id ? (
          <div className="text-gray-600 italic">Self study</div>
        ) : (
          <>
            {viewMode !== 'teacher' && <div className="text-gray-600">{props.teacherName(entry.teacher_id)}</div>}
            {viewMode !== 'room' && <div className="text-gray-600">{props.roomName(entry.room_id)}</div>}
          </>
        )}
      </div>
    );
  };

  const renderDay = (day: string, period: number) => {
    const slot = slotMap.get(`${day}-${period}`);
    const here = cellEntries(day, period);
    const tilesHere = cellTiles(day, period);
    const drop = dropClass(day, period);
    const canAdd = editable && !!slot && here.length === 0 && tilesHere.length === 0 && !dragging;
    return (
      <td
        key={`${day}-${period}`}
        title={drop.title || (slot ? timeLabel(slot) : 'No class slot configured')}
        className={`p-1 border border-gray-100 min-h-[60px] align-top ${drop.cls}`}
        onDragOver={(ev) => { if (editable && dragging && slot) ev.preventDefault(); }}
        onDrop={(ev) => { ev.preventDefault(); if (slot) props.onDrop(day, period); }}
      >
        {here.length || tilesHere.length ? (
          <div className="space-y-1">{here.map(renderCard)}{tilesHere.map((t) => renderFirstYearTile(t, period))}</div>
        ) : slot ? (
          <button
            type="button"
            disabled={!canAdd}
            onClick={() => props.onEmptyClick(day, period)}
            className={`h-full w-full min-h-[44px] flex items-center justify-center text-xs rounded ${canAdd ? 'text-gray-300 hover:text-blue-600 hover:bg-blue-50' : 'text-gray-300'}`}
            title={canAdd ? 'Add a class here' : undefined}
          >
            {canAdd ? <Plus size={14} /> : 'Free'}
          </button>
        ) : <div className="h-full bg-gray-50" />}
      </td>
    );
  };

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-x-auto">
      {props.dragLoading && (
        <div className="px-3 py-1 text-xs text-blue-700 bg-blue-50 border-b border-blue-100">Checking which slots are free...</div>
      )}
      <table className="w-full border-collapse">
        <thead>
          <tr className="bg-gray-100">
            <th className="px-4 py-2 text-left font-medium text-gray-700">Time</th>
            {DAYS.map((day) => (
              <th key={day} className="px-4 py-2 text-center font-medium text-gray-700">{DAY_LABELS[day]}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {periods.map((period) => (
            <tr key={period} className="border-b border-gray-200">
              <td className="px-4 py-2 font-medium text-gray-600 whitespace-nowrap">
                <div>Period {period}</div>
                <div className="text-xs text-gray-400">{timeLabel(slots.find((s) => s.period_index === period))}</div>
              </td>
              {(() => {
                const cells: JSX.Element[] = [];
                let i = 0;
                while (i < DAYS.length) {
                  const day = DAYS[i];
                  if (cellEntries(day, period).length === 0 && cellTiles(day, period).length === 0 && isLunchSlot(day, period)) {
                    const spanStart = i;
                    while (i < DAYS.length && cellEntries(DAYS[i], period).length === 0 && cellTiles(DAYS[i], period).length === 0 && isLunchSlot(DAYS[i], period)) i += 1;
                    cells.push(
                      <td key={`lunch-${period}-${spanStart}`} colSpan={i - spanStart}
                        className="p-1 border border-gray-100 bg-gray-50 text-center text-xs italic text-gray-400">
                        Lunch
                      </td>,
                    );
                    continue;
                  }
                  i += 1;
                  cells.push(renderDay(day, period));
                }
                return cells;
              })()}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
