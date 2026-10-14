import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session

from app import repository
from app.db import get_session
from app.game import contracts, engine, manager, power, rookies, transfers, views
from app.game.catalog import get_catalog
from app.game.errors import IllegalAction
from app.game.state import Action

router = APIRouter(prefix="/api/careers", tags=["careers"])


class NewCareer(BaseModel):
    manager: str = "Manager"
    team: str
    seed: int | None = None


def _cat(career):
    """The catalog this career sees: every catalog player plus its own rookies."""
    return rookies.catalog_for(get_catalog(), career)


def _load(session: Session, save_id: str, fresh: bool = False):
    found = repository.load_save(session, save_id, fresh)
    if found is None:
        raise HTTPException(404, "No such career")
    save, career = found
    # A save from an older version is brought up to date the first time it is opened.
    if engine.migrate(_cat(career), career):
        repository.store(session, save, career, cache=not fresh)
    return save, career


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
    return views.career_view(_cat(career), career, save.id)


@router.delete("/{save_id}", status_code=204)
def remove(save_id: str, session: Session = Depends(get_session)) -> None:
    save, _ = _load(session, save_id)
    repository.delete_save(session, save)


@router.post("/{save_id}/actions")
def act(save_id: str, action: Action, session: Session = Depends(get_session)) -> dict:
    save, career = _load(session, save_id, fresh=True)
    try:
        outcome = engine.apply(_cat(career), career, action)
    except IllegalAction as exc:
        raise HTTPException(409, str(exc)) from exc
    repository.store(session, save, career, outcome.details)
    return {
        # Built after the action: an off-season that just started may have brought new rookies.
        "career": views.career_view(_cat(career), career, save.id),
        "games": [{"match": d.match, "game": d.game} for d in outcome.details],
    }


@router.get("/{save_id}/draft")
def draft(save_id: str, session: Session = Depends(get_session)) -> dict:
    _, career = _load(session, save_id)
    if career.league not in career.drafts:
        raise HTTPException(404, "No draft this season")
    return views.draft_view(_cat(career), career)


@router.get("/{save_id}/squad")
def squad(save_id: str, team: str | None = None, session: Session = Depends(get_session)) -> dict:
    _, career = _load(session, save_id)
    if team is not None and team not in career.teams:
        raise HTTPException(404, "No such team")
    return views.squad_view(_cat(career), career, team)


@router.get("/{save_id}/players")
def players(save_id: str, region: str | None = None, free_agents: bool = False, role: str | None = None,
            rookies_only: bool = False, limit: int = Query(200, le=2000),
            session: Session = Depends(get_session)) -> list[dict]:
    _, career = _load(session, save_id)
    return views.players_search(_cat(career), career, region, free_agents, role, limit, rookies_only)


@router.get("/{save_id}/players/{player_id}")
def player(save_id: str, player_id: str, session: Session = Depends(get_session)) -> dict:
    _, career = _load(session, save_id)
    cat = _cat(career)
    if player_id not in cat.players:
        raise HTTPException(404, "No such player")
    return views.player_detail(cat, career, player_id)


@router.get("/{save_id}/staff")
def staff(save_id: str, kind: str | None = None, region: str | None = None, free_only: bool = False,
          limit: int = Query(200, le=1000), session: Session = Depends(get_session)) -> list[dict]:
    _, career = _load(session, save_id)
    return views.staff_search(_cat(career), career, kind, region, free_only, limit)


@router.get("/{save_id}/staff/{staff_id}")
def staff_member(save_id: str, staff_id: str, session: Session = Depends(get_session)) -> dict:
    _, career = _load(session, save_id)
    cat = _cat(career)
    if staff_id not in cat.staff:
        raise HTTPException(404, "No such staff member")
    return views.staff_detail(cat, career, staff_id)


@router.get("/{save_id}/competitions")
def competitions(save_id: str, session: Session = Depends(get_session)) -> list[dict]:
    _, career = _load(session, save_id)
    return views.competitions_view(_cat(career), career)


@router.get("/{save_id}/competitions/{comp_id}")
def competition(save_id: str, comp_id: str, session: Session = Depends(get_session)) -> dict:
    _, career = _load(session, save_id)
    comp = career.competitions.get(comp_id)
    if comp is None:
        raise HTTPException(404, "No such competition")
    return views.competition_view(_cat(career), career, comp)


@router.get("/{save_id}/schedule")
def schedule(save_id: str, team: str | None = None, session: Session = Depends(get_session)) -> list[dict]:
    _, career = _load(session, save_id)
    return views.schedule_view(_cat(career), career, team)


@router.get("/{save_id}/matches/{match_id}")
def match(save_id: str, match_id: str, session: Session = Depends(get_session)) -> dict:
    _, career = _load(session, save_id)
    m = career.matches.get(match_id)
    if m is None:
        raise HTTPException(404, "No such match")
    return views.match_view(_cat(career), career, m)


@router.get("/{save_id}/matches/{match_id}/games/{number}")
def game(save_id: str, match_id: str, number: int, session: Session = Depends(get_session)) -> dict:
    save, career = _load(session, save_id)
    m = career.matches.get(match_id)
    record = next((g for g in m.games if g.number == number), None) if m else None
    if record is None:
        raise HTTPException(404, "No such game")
    detail = repository.game_detail(session, save.id, match_id, number)
    return {"game": views.game_summary(_cat(career), record), "timeline": detail}


@router.get("/{save_id}/live")
def live(save_id: str, session: Session = Depends(get_session)) -> dict | None:
    _, career = _load(session, save_id)
    return views.live_view(_cat(career), career)


@router.get("/{save_id}/meta")
def meta(save_id: str, session: Session = Depends(get_session)) -> dict:
    _, career = _load(session, save_id)
    return views.meta_view(_cat(career), career)


@router.get("/{save_id}/negotiate/{player_id}")
def negotiation(save_id: str, player_id: str, session: Session = Depends(get_session)) -> dict:
    _, career = _load(session, save_id)
    cat = _cat(career)
    if player_id not in cat.players:
        raise HTTPException(404, "No such player")
    return contracts.negotiation_view(cat, career, player_id)


@router.get("/{save_id}/training")
def training(save_id: str, session: Session = Depends(get_session)) -> dict:
    _, career = _load(session, save_id)
    return views.training_view(_cat(career), career)


@router.get("/{save_id}/manager")
def manager_profile(save_id: str, session: Session = Depends(get_session)) -> dict:
    _, career = _load(session, save_id)
    return manager.view(_cat(career), career)


@router.get("/{save_id}/power")
def power_rankings(save_id: str, session: Session = Depends(get_session)) -> dict:
    _, career = _load(session, save_id)
    return power.view(_cat(career), career)


@router.get("/{save_id}/board")
def board(save_id: str, session: Session = Depends(get_session)) -> dict:
    _, career = _load(session, save_id)
    return views.board_view(_cat(career), career)


@router.get("/{save_id}/transfers")
def transfer_window(save_id: str, session: Session = Depends(get_session)) -> dict:
    _, career = _load(session, save_id)
    return transfers.view(_cat(career), career)


@router.get("/{save_id}/shortlist")
def shortlist(save_id: str, session: Session = Depends(get_session)) -> list[dict]:
    _, career = _load(session, save_id)
    return views.shortlist_view(_cat(career), career)
