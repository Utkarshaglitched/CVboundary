from __future__ import annotations

import os
from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy.orm import Session

from models import IntrusionLog


def create_log(
    db: Session,
    *,
    image_path: str,
    recognized_people: str = "Pending",
    embeddings_path: str | None = None,
    status: str = "INTRUSION",
) -> IntrusionLog:
    entry = IntrusionLog(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
        image_path=image_path,
        embeddings_path=embeddings_path,
        recognized_people=recognized_people,
        status=status,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def list_logs(db: Session, *, query: str | None = None, filter_kind: str | None = None, sort_newest: bool = True) -> Sequence[IntrusionLog]:
    items = db.query(IntrusionLog)
    if query:
        q = query.lower()
        items = items.filter(
            IntrusionLog.recognized_people.ilike(f"%{q}%")
            | IntrusionLog.timestamp.ilike(f"%{q}%")
            | IntrusionLog.status.ilike(f"%{q}%")
        )

    if filter_kind == "known":
        items = items.filter(IntrusionLog.recognized_people.notilike("%unknown%"))
    elif filter_kind == "unknown":
        items = items.filter(IntrusionLog.recognized_people.ilike("%unknown%"))
    elif filter_kind == "multiple":
        items = items.filter(IntrusionLog.recognized_people.contains(","))

    if sort_newest:
        items = items.order_by(IntrusionLog.id.desc())
    else:
        items = items.order_by(IntrusionLog.id.asc())
    return items.all()


def get_log(db: Session, log_id: int) -> Optional[IntrusionLog]:
    return db.query(IntrusionLog).filter(IntrusionLog.id == log_id).first()


def _remove_file(path: str | None) -> None:
    if path and os.path.exists(path):
        os.remove(path)


def delete_log(db: Session, log_id: int) -> bool:
    entry = get_log(db, log_id)
    if not entry:
        return False
    _remove_file(entry.image_path)
    _remove_file(entry.embeddings_path)
    db.delete(entry)
    db.commit()
    return True


def delete_all_logs(db: Session) -> int:
    entries = db.query(IntrusionLog).all()
    for entry in entries:
        _remove_file(entry.image_path)
        _remove_file(entry.embeddings_path)
    count = len(entries)
    db.query(IntrusionLog).delete()
    db.commit()
    return count
