"""One-off data fix for the "N batches, only M teachers" generation failure.

Every lab in this department was on batch_scheduling_mode='independent',
which the solver has to read conservatively as "these batches may all run
at once" - so a 3-batch lab was treated as needing 3 qualified teachers,
and generation was blocked for nine subjects at once.

Two different fixes apply, because two different situations are mixed in:

  * A section with at least as many equal-length labs as it has batches can
    ROTATE them: all its labs run at the same time with a different batch
    in each, swapping round by round. Each lab then only ever runs with one
    batch at a time, so one qualified teacher per lab is enough. That is
    what the LabRotationGroup rows below set up.

  * A section with FEWER such labs than batches cannot form a rotation -
    there would be nothing for the spare batch to do in a round. Those labs
    get batch_scheduling_mode='sequential' instead: their batches never
    overlap, so again one teacher covers all of them, one after another.
    It costs more slots in the week than a rotation, which is why it is the
    fallback and not the default.

Re-runnable: existing rotation rows with these ids are updated in place.
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal  # noqa: E402
from app.models import LabBatch, LabRotationGroup, Subject  # noqa: E402

DEPARTMENT_ID = "cse"
REASON = "Set up from the lab-rotation data fix (see scripts/setup_lab_rotations.py)"

# section_id -> (rotation id, name, [subject ids]). Each list is every
# 2-period lab that section takes, so the rotation has at least as many
# rounds as the section has batches.
ROTATIONS = {
    "SEC_II_A": ("rot_sec_ii_a", "2nd year A labs", ["CO24401", "CO24402", "CO24404"]),
    "SEC_II_B": ("rot_sec_ii_b", "2nd year B labs", ["CO24801", "CO24802", "CO24804_LAB"]),
    "SEC_III_B": ("rot_sec_iii_b", "3rd year B labs", ["CO34801", "CO34802", "CO34803", "CO34804_LAB"]),
}

# Labs whose section hasn't enough equal-length labs to rotate. Each is
# taken by exactly one section, so changing the subject changes nothing
# elsewhere.
SEQUENTIAL = [
    "CO34401",          # CN Lab - SEC_III_A has only two 2-period labs for three batches
    "CO34402",          # OS Lab - same section, same reason
    "CO34482",          # Internship (1 period) - nothing of equal length to rotate with
    "IV_INTERNSHIP_A",  # 1 teacher, 3 batches
    "IV_INTERNSHIP_B",  # 1 teacher, 3 batches
]


def main(apply: bool) -> None:
    db = SessionLocal()
    try:
        planned = []

        for section_id, (rotation_id, name, subject_ids) in ROTATIONS.items():
            batches = db.query(LabBatch).filter(LabBatch.section_id == section_id).count()
            subjects = [db.get(Subject, sid) for sid in subject_ids]
            missing = [sid for sid, s in zip(subject_ids, subjects) if s is None]
            if missing:
                print(f"SKIP {rotation_id}: unknown subject(s) {missing}")
                continue
            if len(subject_ids) < batches:
                print(f"SKIP {rotation_id}: {len(subject_ids)} labs for {batches} batches")
                continue
            existing = db.get(LabRotationGroup, rotation_id)
            verb = "update" if existing else "create"
            planned.append(
                f"{verb} rotation {rotation_id}: {section_id} ({batches} batches) rotates "
                f"{', '.join(s.name for s in subjects)}"
            )
            if not apply:
                continue
            record = existing or LabRotationGroup(id=rotation_id)
            record.department_id = DEPARTMENT_ID
            record.section_id = section_id
            record.name = name
            record.subject_ids = subject_ids
            # Deliberately unpinned: each round is its own 2-period block,
            # and no single afternoon window on this bell schedule holds
            # three or four of them. Pinning one would make the rotation
            # infeasible instead of merely unplaced.
            record.day = None
            record.start_time = None
            record.end_time = None
            record.source = "manual"
            record.raw_instruction = REASON
            record.is_active = True
            db.add(record)

        for subject_id in SEQUENTIAL:
            subject = db.get(Subject, subject_id)
            if subject is None:
                print(f"SKIP sequential {subject_id}: unknown subject")
                continue
            if subject.batch_scheduling_mode == "sequential":
                continue
            planned.append(
                f"set {subject_id} ({subject.name}) batch mode "
                f"{subject.batch_scheduling_mode} -> sequential"
            )
            if apply:
                subject.batch_scheduling_mode = "sequential"

        for line in planned:
            print(("APPLIED " if apply else "WOULD   ") + line)
        if apply:
            db.commit()
            print(f"\nCommitted {len(planned)} change(s).")
        else:
            print(f"\nDry run: {len(planned)} change(s). Re-run with --apply to write them.")
    finally:
        db.close()


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
