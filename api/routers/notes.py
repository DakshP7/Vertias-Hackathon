from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import DOCTOR, RADIOLOGIST, audit, current_user, get_patient_or_404, require_roles
from ..models import Note, Scan, User
from ..schemas import NoteIn, NoteOut

router = APIRouter(prefix="/patients/{patient_id}/notes", tags=["notes"])


def _out(note: Note, author: User) -> NoteOut:
    return NoteOut(id=note.id, patient_id=note.patient_id, scan_id=note.scan_id, author_id=author.id,
                   author_name=author.full_name, author_role=author.role, text=note.text, created_at=note.created_at)


@router.get("", response_model=list[NoteOut])
def list_notes(patient_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    get_patient_or_404(db, patient_id)
    rows = db.execute(
        select(Note, User).join(User, User.id == Note.author_id)
        .where(Note.patient_id == patient_id).order_by(Note.created_at)
    ).all()
    return [_out(n, u) for n, u in rows]


@router.post("", response_model=NoteOut, status_code=201)
def add_note(patient_id: int, body: NoteIn, user: User = Depends(require_roles(RADIOLOGIST, DOCTOR)),
             db: Session = Depends(get_db)):
    get_patient_or_404(db, patient_id)
    if body.scan_id is not None:
        scan = db.get(Scan, body.scan_id)
        if not scan or scan.patient_id != patient_id:
            raise HTTPException(400, "scan_id does not belong to this patient")
    note = Note(patient_id=patient_id, scan_id=body.scan_id, author_id=user.id, text=body.text)
    db.add(note)
    db.commit()
    audit(db, user, "add_note", patient_id, f"note={note.id}")
    return _out(note, user)
