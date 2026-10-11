"""Careers that take a while to build, shared by every test module."""

import pytest

from app.game import engine
from app.game.catalog import get_catalog
from app.game.state import AcceptJobAction, AdvanceAction, BoardMeetingAction, DraftSimAction, SimSeriesAction

cat = get_catalog()


@pytest.fixture(scope="session")
def drafted():
    """G2 after the draft, on the first day of the season. Copy it before changing it."""
    career = engine.new_career(cat, "Tester", "G2", 42)
    engine.apply(cat, career, BoardMeetingAction(type="board_meeting"))
    engine.apply(cat, career, DraftSimAction(type="draft_sim"))
    return career


@pytest.fixture(scope="session")
def finished(drafted):
    """The same career the day the Worlds final is played, at the start of the off-season."""
    career = drafted.model_copy(deep=True)
    for _ in range(600):
        if career.phase != "season":
            break
        if career.board.sacked:
            engine.apply(cat, career, AcceptJobAction(type="accept_job", team=career.job_offers[0]))
        if career.board.meeting:
            engine.apply(cat, career, BoardMeetingAction(type="board_meeting"))
        if career.live:
            engine.apply(cat, career, SimSeriesAction(type="sim_series"))
        else:
            engine.apply(cat, career, AdvanceAction(type="advance"))
    return career
