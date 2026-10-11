import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session

from app import repository
from app.db import get_session
from app.game import contracts, engine, views
from app.game.catalog import get_catalog
from app.game.errors import IllegalAction
from app.game.state import Action

router = APIRouter(prefix="/api/careers", tags=["careers"])


class NewCareer(BaseModel):
    manager: str = "Manager"
    team: str
    seed: int | None = None


def _load(session: Session, save_id: str):
    found = repository.load_save(session, save_id)
    if found is None:
        raise HTTPException(404, "No such career")
    return found


@router.post("")
def create(body: NewCareer, session: Session = Depends(get_session)) -> dict:
    cat = get_catalog()
    try:
        career = engine.new_career(cat, body.manager, body.team, body.seed or secrets.randbits(32))
    except IllegalAction as exc:
        raise HTTPException(400, str(exc)) from exc
    save = repository.create_save(session, career)
    return views.career_view(cat, career, save.id)


@router.get("")
def list_careers(limit: int = Query(20, le=50), session: Session = Depends(get_session)) -> list[dict]:
    cat = get_catalog()
    return [views.save_row(s, cat) for s in repository.recent_saves(session, limit)]


@router.get("/{save_id}")
def get(save_id: str, session: Session = Depends(get_session)) -> dict:
    save, career = _load(session, save_id)
    return views.career_view(get_catalog(), career, save.id)


@router.delete("/{save_id}", status_code=204)
def remove(save_id: str, session: Session = Depends(get_session)) -> None:
    save, _ = _load(session, save_id)
    repository.delete_save(session, save)


@router.post("/{save_id}/actions")
def act(save_id: str, action: Action, session: Session = Depends(get_session)) -> dict:
    cat = get_catalog()
    save, career = _load(session, save_id)
    try:
        outcome = engine.apply(cat, career, action)
    except IllegalAction as exc:
        raise HTTPException(409, str(exc)) from exc
    repository.store(session, save, career, outcome.details)
    return {
        "career": views.career_view(cat, career, save.id),
        "games": [{"match": d.match, "game": d.game} for d in outcome.details],
    }


@router.get("/{save_id}/draft")
def draft(save_id: str, session: Session = Depends(get_session)) -> dict:
    _, career = _load(session, save_id)
    if career.league not in career.drafts:
        raise HTTPException(404, "No draft this season")
    return views.draft_view(get_catalog(), career)


@router.get("/{save_id}/squad")
def squad(save_id: str, team: str | None = None, session: Session = Depends(get_session)) -> dict:
    _, career = _load(session, save_id)
    if team is not None and team not in career.teams:
        raise HTTPException(404, "No such team")
    return views.squad_view(get_catalog(), career, team)


@router.get("/{save_id}/players")
def players(save_id: str, region: str | None = None, free_agents: bool = False, role: str | None = None,
            limit: int = Query(200, le=2000), session: Session = Depends(get_session)) -> list[dict]:
    _, career = _load(session, save_id)
    return views.players_search(get_catalog(), career, region, free_agents, role, limit)


@router.get("/{save_id}/players/{player_id}")
def player(save_id: str, player_id: str, session: Session = Depends(get_session)) -> dict:
    _, career = _load(session, save_id)
    cat = get_catalog()
    if player_id not in cat.players:
        raise HTTPException(404, "No such player")
    return views.player_detail(cat, career, player_id)


@router.get("/{save_id}/competitions")
def competitions(save_id: str, session: Session = Depends(get_session)) -> list[dict]:
    _, career = _load(session, save_id)
    return views.competitions_view(get_catalog(), career)


@router.get("/{save_id}/competitions/{comp_id}")
def competition(save_id: str, comp_id: str, session: Session = Depends(get_session)) -> dict:
    _, career = _load(session, save_id)
    comp = career.competitions.get(comp_id)
    if comp is None:
        raise HTTPException(404, "No such competition")
    return views.competition_view(get_catalog(), career, comp)


@router.get("/{save_id}/schedule")
def schedule(save_id: str, team: str | None = None, session: Session = Depends(get_session)) -> list[dict]:
    _, career = _load(session, save_id)
    return views.schedule_view(get_catalog(), career, team)


@router.get("/{save_id}/matches/{match_id}")
def match(save_id: str, match_id: str, session: Session = Depends(get_session)) -> dict:
    _, career = _load(session, save_id)
    m = career.matches.get(match_id)
    if m is None:
        raise HTTPException(404, "No such match")
    return views.match_view(get_catalog(), career, m)


@router.get("/{save_id}/matches/{match_id}/games/{number}")
def game(save_id: str, match_id: str, number: int, session: Session = Depends(get_session)) -> dict:
    save, career = _load(session, save_id)
    m = career.matches.get(match_id)
    record = next((g for g in m.games if g.number == number), None) if m else None
    if record is None:
        raise HTTPException(404, "No such game")
    detail = repository.game_detail(session, save.id, match_id, number)
    return {"game": views.game_summary(get_catalog(), record), "timeline": detail}


@router.get("/{save_id}/live")
def live(save_id: str, session: Session = Depends(get_session)) -> dict | None:
    _, career = _load(session, save_id)
    return views.live_view(get_catalog(), career)


@router.get("/{save_id}/meta")
def meta(save_id: str, session: Session = Depends(get_session)) -> dict:
    _, career = _load(session, save_id)
    return views.meta_view(get_catalog(), career)


@router.get("/{save_id}/negotiate/{player_id}")
def negotiation(save_id: str, player_id: str, session: Session = Depends(get_session)) -> dict:
    _, career = _load(session, save_id)
    cat = get_catalog()
    if player_id not in cat.players:
        raise HTTPException(404, "No such player")
    return contracts.negotiation_view(cat, career, player_id)
