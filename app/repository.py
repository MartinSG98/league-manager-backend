import json
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


def load_save(session: Session, save_id: str) -> tuple[Save, Career] | None:
    save = session.get(Save, save_id)
    if save is None:
        return None
    return save, Career.model_validate_json(save.state)


def store(session: Session, save: Save, career: Career, details: list[Detail] = ()) -> None:  # type: ignore[assignment]
    save.season = career.season
    save.day = career.day
    save.phase = career.phase
    save.state = career.model_dump_json()
    save.updated_at = _utcnow()
    session.add(save)
    for d in details:
        session.merge(GameDetail(save_id=save.id, match_id=d.match, game=d.game, payload=json.dumps(d.payload)))
    session.commit()


def recent_saves(session: Session, limit: int) -> list[Save]:
    return list(session.exec(select(Save).order_by(col(Save.updated_at).desc()).limit(limit)).all())


def delete_save(session: Session, save: Save) -> None:
    session.exec(delete(GameDetail).where(col(GameDetail.save_id) == save.id))  # type: ignore[call-overload]
    session.delete(save)
    session.commit()


def game_detail(session: Session, save_id: str, match_id: str, game: int) -> dict | None:
    row = session.get(GameDetail, (save_id, match_id, game))
    return json.loads(row.payload) if row else None
