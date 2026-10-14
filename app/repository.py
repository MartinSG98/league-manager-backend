import json
from datetime import datetime
from uuid import uuid4

from sqlmodel import Session, col, delete, select

from app.game.matchday import Detail
from app.game.state import Career
from app.models import GameDetail, Save, _utcnow


def create_save(session: Session, career: Career) -> Save:
    save = Save(
        id=uuid4().hex, manager=career.manager, team=career.team, season=career.season, day=career.day,
        phase=career.phase, state=career.model_dump_json(),
    )
    session.add(save)
    session.commit()
    session.refresh(save)
    return save


# Parsed careers by save id, for reads. A save grows to several megabytes and takes tens of
# milliseconds to parse, and every click in the UI is followed by half a dozen reads. An action
# parses its own copy, since it changes it and one that fails half way must leave nothing behind,
# and the copy it stores becomes the cached one.
_parsed: dict[str, tuple[datetime, Career]] = {}


def _stamp(moment: datetime) -> datetime:
    """SQLite gives the time back without its time zone; compare both the same way."""
    return moment.replace(tzinfo=None)


def load_save(session: Session, save_id: str, fresh: bool = False) -> tuple[Save, Career] | None:
    """The save and its career. Reads share one parsed career per save; with `fresh` the career
    is the caller's own, to change."""
    save = session.get(Save, save_id)
    if save is None:
        _parsed.pop(save_id, None)
        return None
    hit = _parsed.get(save_id)
    if not fresh and hit is not None and hit[0] == _stamp(save.updated_at):
        return save, hit[1]
    career = Career.model_validate_json(save.state)
    if not fresh:
        _parsed[save_id] = (_stamp(save.updated_at), career)
    return save, career


def store(session: Session, save: Save, career: Career, details: list[Detail] = (),  # type: ignore[assignment]
          cache: bool = True) -> None:
    """Write the career back. With `cache` it also becomes the career reads get; an action that
    stores a migrated copy before running passes False, since it may still fail on that copy."""
    save.season = career.season
    save.day = career.day
    save.phase = career.phase
    save.state = career.model_dump_json()
    stamp = _utcnow()
    save.updated_at = stamp
    session.add(save)
    for d in details:
        session.merge(GameDetail(save_id=save.id, match_id=d.match, game=d.game, payload=json.dumps(d.payload)))
    session.commit()
    if cache:
        _parsed[save.id] = (_stamp(stamp), career)
    else:
        _parsed.pop(save.id, None)


def recent_saves(session: Session, limit: int) -> list[Save]:
    return list(session.exec(select(Save).order_by(col(Save.updated_at).desc()).limit(limit)).all())


def delete_save(session: Session, save: Save) -> None:
    _parsed.pop(save.id, None)
    session.exec(delete(GameDetail).where(col(GameDetail.save_id) == save.id))  # type: ignore[call-overload]
    session.delete(save)
    session.commit()


def game_detail(session: Session, save_id: str, match_id: str, game: int) -> dict | None:
    row = session.get(GameDetail, (save_id, match_id, game))
    return json.loads(row.payload) if row else None
