from datetime import date, datetime, timezone

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Save(SQLModel, table=True):
    id: str = Field(primary_key=True)
    manager: str
    team: str = Field(index=True)
    season: int
    day: date
    phase: str
    state: str  # Career as JSON, the game engine owns its shape
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow, index=True)


class GameDetail(SQLModel, table=True):
    """The timeline of one game the manager played, kept out of the career document."""

    save_id: str = Field(primary_key=True)
    match_id: str = Field(primary_key=True)
    game: int = Field(primary_key=True)
    payload: str  # {"events": [...], "gold": [...]} as JSON
