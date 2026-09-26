import { useEffect, useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { CheckCircle2, Circle } from 'lucide-react';
import {
  yearsApi, sectionsApi, subjectsApi, electiveGroupsApi, constraintsApi, teachersApi, roomsApi,
} from '../api/client';
import { Section, Subject, AcademicYear, SectionSubject, LabBatch, ElectiveGroup } from '../types';

interface StepStatus {
  complete: boolean;
  issueCount: number;
}

interface SetupData {
  years: AcademicYear[];
  sections: Section[];
  subjects: Subject[];
  sectionSubjects: SectionSubject[];
  labBatches: LabBatch[];
  electiveGroups: (ElectiveGroup & { _infeasible: boolean })[];
  qualificationsMap: Record<string, string[]>;
  teachersCount: number;
  roomsCount: number;
}

interface SetupStep {
  path: string;
  label: string;
  status: (d: SetupData) => StepStatus;
}

const STEPS: SetupStep[] = [
  {
    path: 'years-sections', label: 'Years & Sections',
    status: (d) => {
      const created: Record<string, number> = {};
      d.sections.forEach((s) => { created[s.year_id] = (created[s.year_id] || 0) + 1; });
      const short = d.years.filter((y) => (created[y.id] || 0) < y.num_sections).length;
      return { complete: d.years.length > 0 && d.sections.length > 0, issueCount: short };
    },
  },
  {
    path: 'subjects', label: 'Subjects',
    status: (d) => {
      const unqualified = d.subjects.filter(
        (s) => s.delivery_mode === 'IN_PERSON' && (d.qualificationsMap[s.id] || []).length === 0
      ).length;
      return { complete: d.subjects.length > 0, issueCount: unqualified };
    },
  },
  {
    path: 'curriculum', label: 'Curriculum',
    status: (d) => {
      const sectionsWithSubjects = new Set(d.sectionSubjects.map((ss) => ss.section_id));
      const empty = d.sections.filter((s) => !sectionsWithSubjects.has(s.id)).length;
      return { complete: d.sectionSubjects.length > 0, issueCount: d.sections.length > 0 ? empty : 0 };
    },
  },
  {
    path: 'electives', label: 'Electives',
    status: (d) => ({ complete: d.electiveGroups.length > 0, issueCount: d.electiveGroups.filter((g) => g._infeasible).length }),
  },
  {
    path: 'lab-batches', label: 'Lab Batches',
    status: (d) => {
      const labSubjectIds = new Set(d.subjects.filter((s) => s.type === 'lab').map((s) => s.id));
      const sectionsWithLab = new Set(
        d.sectionSubjects.filter((ss) => labSubjectIds.has(ss.subject_id)).map((ss) => ss.section_id)
      );
      const sectionsWithBatches = new Set(d.labBatches.map((b) => b.section_id));
      const missing = [...sectionsWithLab].filter((id) => !sectionsWithBatches.has(id)).length;
      return { complete: d.labBatches.length > 0, issueCount: missing };
    },
  },
  { path: 'teachers', label: 'Teachers', status: (d) => ({ complete: d.teachersCount > 0, issueCount: 0 }) },
  { path: 'rooms', label: 'Rooms', status: (d) => ({ complete: d.roomsCount > 0, issueCount: 0 }) },
  { path: 'import', label: 'Import from Excel', status: () => ({ complete: true, issueCount: 0 }) },
];

/** A persistent left sub-nav for Setup with completion ticks AND a
 * blocking-issues count per page, replacing the old wizard's linear
 * progress bar (Phase 3.2/3.10) - an admin can jump straight to any step
 * and see at a glance both what's untouched and what's actively wrong. */
export function SetupLayout() {
  const [data, setData] = useState<SetupData | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      yearsApi.list(), sectionsApi.list(), subjectsApi.list(),
      constraintsApi.getAllSectionSubjects(), constraintsApi.getAllLabBatches(),
      electiveGroupsApi.list(), subjectsApi.getTeacherQualificationsMap(),
      teachersApi.list(), roomsApi.list(),
    ]).then(async ([years, sections, subjects, sectionSubjects, labBatches, electiveGroups, qualMap, teachers, rooms]) => {
      // Feasibility needs one preflight call per basket with 2+ offered
      // options - baskets are few per department, so this stays cheap.
      const groups: ElectiveGroup[] = electiveGroups.data;
      const withFeasibility = await Promise.all(groups.map(async (g) => {
        if ((g.offered_subject_ids || []).length < 2) return { ...g, _infeasible: false };
        try {
          const preflight = await electiveGroupsApi.preflight(g.id);
          return { ...g, _infeasible: !preflight.data.feasible };
        } catch {
          return { ...g, _infeasible: false };
        }
      }));
      if (cancelled) return;
      setData({
        years: years.data, sections: sections.data, subjects: subjects.data,
        sectionSubjects: sectionSubjects.data, labBatches: labBatches.data,
        electiveGroups: withFeasibility, qualificationsMap: qualMap.data,
        teachersCount: teachers.data.length, roomsCount: rooms.data.length,
      });
    }).catch(() => setData(null));
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="grid grid-cols-1 md:grid-cols-[240px_1fr] gap-6">
      <nav className="space-y-1">
        {STEPS.map((step) => {
          const status = data ? step.status(data) : { complete: false, issueCount: 0 };
          return (
            <NavLink
              key={step.path}
              to={`/setup/${step.path}`}
              className={({ isActive }) =>
                `flex items-center justify-between gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
                  isActive ? 'bg-blue-50 text-blue-700 font-medium' : 'text-gray-700 hover:bg-gray-100'
                }`
              }
            >
              <span>{step.label}</span>
              <span className="flex items-center gap-1.5 shrink-0">
                {status.issueCount > 0 && (
                  <span className="rounded-full bg-red-100 px-1.5 py-0.5 text-xs font-medium text-red-700" title="Blocking issues on this page">
                    {status.issueCount}
                  </span>
                )}
                {status.complete
                  ? <CheckCircle2 size={16} className="text-green-500 shrink-0" />
                  : <Circle size={16} className="text-gray-300 shrink-0" />}
              </span>
            </NavLink>
          );
        })}
      </nav>
      <div className="min-w-0">
        <Outlet />
      </div>
    </div>
  );
}
