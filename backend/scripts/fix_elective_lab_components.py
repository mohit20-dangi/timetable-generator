"""Takes lab COMPONENTS back out of the elective baskets they were imported into.

An elective group holds ALTERNATIVES - a student picks one of them - so the
solver runs every member at the same time, which is the whole point of a
basket. Two of the imported baskets instead hold the theory and the lab of
ONE elective, which the same students both attend. Forcing those to the same
slot means putting one cohort in two places at once, so the model was
unsatisfiable by construction and generation returned a bare INFEASIBLE for
both repeater sections.

The two are recognisable without guessing: their members share a
`linked_group_id`, which is exactly how this codebase already marks "these
rows are the L/T/P parts of one curriculum entry" (see Subject's docstring).
So the lab is removed from the basket and left linked to its theory, and it
is then scheduled normally, at its own time, with its own batches.

Only labs are moved. A tutorial sibling in a basket (EG_III_EI) has the same
modelling problem but does NOT block generation today - both its members are
section-level, so the solver collapses them into one interval instead of
deadlocking - and taking it out would change a section that currently
schedules fine. It is reported, not changed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal  # noqa: E402
from app.models import ElectiveGroup, SectionSubject, Subject  # noqa: E402


def main(apply: bool) -> None:
    db = SessionLocal()
    try:
        changes, notes = [], []
        for group in db.query(ElectiveGroup).all():
            member_ids = list(group.offered_subject_ids or [])
            members = [(sid, db.get(Subject, sid)) for sid in member_ids]
            members = [(sid, s) for sid, s in members if s is not None]

            # Components of one course, not alternatives: same linked_group_id.
            by_link = {}
            for sid, subject in members:
                if subject.linked_group_id:
                    by_link.setdefault(subject.linked_group_id, []).append((sid, subject))

            remove = []
            for link_id, siblings in by_link.items():
                if len(siblings) < 2:
                    continue
                labs = [(sid, s) for sid, s in siblings if s.type == "lab"]
                if not labs:
                    notes.append(
                        f"{group.id}: {', '.join(s.name for _sid, s in siblings)} are components of "
                        f"one course ({link_id}) but none is a lab - left alone, it does not block "
                        "generation. Consider taking the non-theory part out of the basket too."
                    )
                    continue
                remove.extend(sid for sid, _s in labs)

            if not remove:
                continue
            kept = [sid for sid in member_ids if sid not in remove]
            changes.append(f"{group.id} ({group.name}): remove {', '.join(remove)}; keep {kept}")
            if not apply:
                continue
            group.offered_subject_ids = kept
            # The section_subjects row carries its own copy of the basket id
            # (it is what data_loader actually reads per section), so both
            # have to be cleared or the lab stays co-scheduled.
            for sid in remove:
                for row in db.query(SectionSubject).filter(
                    SectionSubject.subject_id == sid,
                    SectionSubject.elective_group_id == group.id,
                ).all():
                    row.elective_group_id = None
                subject = db.get(Subject, sid)
                if subject is not None and subject.elective_group_id == group.id:
                    subject.elective_group_id = None

        for line in changes:
            print(("APPLIED " if apply else "WOULD   ") + line)
        for line in notes:
            print("NOTE    " + line)
        if apply:
            db.commit()
            print(f"\nCommitted {len(changes)} change(s).")
        else:
            print(f"\nDry run: {len(changes)} change(s). Re-run with --apply to write them.")
    finally:
        db.close()


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
