"""The analyst's predictions before splits and international events."""

from app.game import predictions
from app.game.catalog import get_catalog
from app.game.rng import Rng

cat = get_catalog()


def test_every_event_and_every_split_of_the_league_gets_predictions(finished):
    subjects = [m.subject for m in finished.inbox if m.subject.startswith("Analyst predictions")]
    for event in ("First Stand", "Mid-Season Invitational", "World Championship"):
        assert sum(event in s for s in subjects) == 1, event
    league = cat.leagues[cat.teams[finished.team].league].name
    assert sum(s.startswith(f"Analyst predictions: {league}") for s in subjects) >= 2
    piece = next(m for m in finished.inbox if m.subject.startswith("Analyst predictions: World Championship"))
    assert piece.kind == "scouting" and "1. " in piece.body and "the playoff line" not in piece.body


def test_a_better_analyst_reads_the_teams_closer_to_their_strength(drafted):
    career = drafted.model_copy(deep=True)
    teams = [t.id for t in cat.league_teams("LEC")]
    truth = sorted(teams, key=lambda t: -predictions.strength(cat, career, t))

    def misses(scouting: float) -> int:
        career.profile.duties["scouting"] = "manager"
        career.profile.attributes["scouting"] = scouting
        total = 0
        for seed in range(20):
            career.rs = seed
            order = predictions.predict(cat, career, teams, Rng(career))
            total += sum(abs(order.index(t) - truth.index(t)) for t in teams)
        return total

    assert misses(20) == 0 and misses(1) > 0
