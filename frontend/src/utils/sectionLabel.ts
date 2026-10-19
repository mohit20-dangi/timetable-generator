import { AcademicYear, Section } from '../types';

/** "Third Year - A": section names repeat across years, so always show the year too. */
export function sectionLabel(section: Section, years: Record<string, AcademicYear>): string {
  const year = years[section.year_id];
  return year ? `${year.name} - ${section.name}` : section.name;
}

export function yearMap(list: AcademicYear[]): Record<string, AcademicYear> {
  const map: Record<string, AcademicYear> = {};
  list.forEach((y) => { map[y.id] = y; });
  return map;
}
