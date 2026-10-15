import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LEAGUE_MANAGER_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    from app import db
    from app.config import get_settings

    get_settings.cache_clear()
    db._engine = None
    from app.main import app

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()
    db._engine = None


def act(client, save_id: str, body: dict) -> dict:
    r = client.post(f"/api/careers/{save_id}/actions", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_catalog_lists_tier_one_teams_and_every_champion(client):
    data = client.get("/api/catalog").json()
    assert {t["league"] for t in data["teams"]} == {"LCK", "LPL", "LEC", "LCS", "CBLOL", "LCP"}
    assert len(data["champions"]) >= 170
    g2 = client.get("/api/catalog/teams/G2").json()
    assert g2["franchise"]["name"] == "Caps"
    assert g2["logo"].startswith("https://") and g2["franchise"]["photo"].startswith("https://")
    assert all(lg["logo"] for lg in data["leagues"])
    assert set(data["event_logos"]) == {"FST", "MSI", "WORLDS"}


def create_manager(client, save, background="coach"):
    """Create the manager the way the client does: the points from the manager view, spread evenly."""
    view = client.get(f"/api/careers/{save}/manager").json()
    assert view["profile"] is None
    attrs = [a["id"] for a in view["attributes"]]
    points = next(b["points"] for b in view["backgrounds"] if b["id"] == background)
    each, extra = divmod(view["rules"]["base"] * len(attrs) + points, len(attrs))
    values = {a: each + (1 if i < extra else 0) for i, a in enumerate(attrs)}
    return act(client, save, {"type": "create_manager", "background": background, "attributes": values})


def test_unknown_team_is_rejected(client):
    assert client.post("/api/careers", json={"team": "NOPE"}).status_code == 400


def test_a_career_from_draft_to_a_played_game(client):
    career = client.post("/api/careers", json={"manager": "Martin", "team": "G2", "seed": 99}).json()
    save = career["id"]
    assert career["phase"] == "draft" and career["draft"]["number"] == 1
    assert career["board"]["meeting"] and career["board"]["objectives"]
    r = client.post(f"/api/careers/{save}/actions", json={"type": "draft_next", "until_mine": True})
    assert r.json()["career"]["draft"]["number"] == 1, "the draft waits for the manager and the board meeting"
    assert career["profile"] is None
    assert client.post(f"/api/careers/{save}/actions", json={"type": "board_meeting"}).status_code == 409
    assert create_manager(client, save)["career"]["profile"]["background"] == "coach"
    meeting = client.get(f"/api/careers/{save}/board").json()
    assert all(len(o["options"]) == 3 for o in meeting["objectives"])
    career = act(client, save, {"type": "board_meeting", "stances": {"split1": 1}})["career"]
    assert not career["board"]["meeting"]
    career = act(client, save, {"type": "draft_next", "until_mine": True})["career"]
    assert career["draft"]["my_turn"]

    board = client.get(f"/api/careers/{save}/draft").json()
    legal = next(p for p in board["pool"] if p["problem"] is None)
    after = act(client, save, {"type": "draft_pick", "player": legal["id"]})["career"]
    assert after["draft"] is None or after["draft"]["number"] > career["draft"]["number"]

    # A second player of the franchise player's role is refused while roles are open.
    board = client.get(f"/api/careers/{save}/draft").json()
    if board["my_turn"]:
        bad = next((p for p in board["pool"] if p["problem"]), None)
        if bad:
            r = client.post(f"/api/careers/{save}/actions", json={"type": "draft_pick", "player": bad["id"]})
            assert r.status_code == 409

    career = act(client, save, {"type": "draft_sim"})["career"]
    assert career["phase"] == "season"
    squad = client.get(f"/api/careers/{save}/squad").json()
    assert len(squad["lineup"]) == 5

    for _ in range(60):
        career = act(client, save, {"type": "advance"})["career"]
        if career["live"]:
            break
    assert career["live"]

    live = client.get(f"/api/careers/{save}/live").json()
    assert live["phase"] == "lineup"
    act(client, save, {"type": "start_champ_select"})
    act(client, save, {"type": "opponent_turn", "until_mine": True})
    live = client.get(f"/api/careers/{save}/live").json()
    turn = live["select"]["turn"]
    if turn:
        assert turn["side"] == live["our_side"]
        assert live["board"]["kind"] == turn["kind"] and live["board"]["champions"]
    if turn and turn["side"] == live["our_side"]:
        option = live["suggestions"][0]
        body = {"type": turn["kind"], "champion": option["champion"]}
        if turn["kind"] == "pick":
            body["role"] = option["role"]
        act(client, save, body)
    act(client, save, {"type": "auto_select"})
    played = act(client, save, {"type": "play_game"})
    assert played["games"]
    g = played["games"][0]
    detail = client.get(f"/api/careers/{save}/matches/{g['match']}/games/{g['game']}").json()
    assert detail["timeline"]["events"][-1]["kind"] == "nexus"
    assert len(detail["game"]["players"]) == 10

    career = act(client, save, {"type": "sim_series"})["career"]
    assert career["live"] is None

    training = client.get(f"/api/careers/{save}/training").json()
    assert len(training["areas"]) == 5 and training["players"]
    act(client, save, {"type": "set_training", "load": "heavy", "focus": ["closing", "early_game"]})
    assert client.get(f"/api/careers/{save}/training").json()["load"] == "heavy"
    window = client.get(f"/api/careers/{save}/transfers").json()
    assert window["open"] is False

    comps = client.get(f"/api/careers/{save}/competitions").json()
    lec = next(c for c in comps if c["league"] == "LEC")
    view = client.get(f"/api/careers/{save}/competitions/{lec['id']}").json()
    assert view["stages"][0]["tables"][0]["rows"]
    assert client.get(f"/api/careers/{save}/meta").json()["champions"]
    assert client.get("/api/careers").json()[0]["id"] == save


def test_actions_out_of_turn_are_conflicts(client):
    save = client.post("/api/careers", json={"team": "T1", "seed": 3}).json()["id"]
    r = client.post(f"/api/careers/{save}/actions", json={"type": "advance"})
    assert r.status_code == 409
    r = client.post(f"/api/careers/{save}/actions", json={"type": "play_game"})
    assert r.status_code == 409


def test_reads_share_a_parsed_career_and_a_failed_action_changes_nothing(client):
    from app import repository

    save = client.post("/api/careers", json={"team": "T1", "seed": 3}).json()["id"]
    create_manager(client, save)
    act(client, save, {"type": "board_meeting"})
    client.get(f"/api/careers/{save}")
    cached = repository._parsed[save][1]
    before = cached.model_dump_json()
    for path in ("", "/board", "/squad", "/draft", "/competitions", "/schedule", "/training", "/transfers",
                 "/meta", "/shortlist", "/players", "/staff"):
        assert client.get(f"/api/careers/{save}{path}").status_code in (200, 404, 409), path
    assert repository._parsed[save][1] is cached, "reads reuse the parsed career"
    assert cached.model_dump_json() == before, "reads change nothing"
    assert client.post(f"/api/careers/{save}/actions", json={"type": "play_game"}).status_code == 409
    assert repository._parsed[save][1] is cached and cached.model_dump_json() == before
    act(client, save, {"type": "draft_next", "until_mine": True})
    assert repository._parsed[save][1] is not cached, "what an action stores is what reads get next"


def test_only_the_saves_used_last_stay_parsed(client):
    from app import repository

    saves = [client.post("/api/careers", json={"team": team, "seed": 3}).json()["id"] for team in ("T1", "G2", "BLG")]
    for save in saves:
        assert client.get(f"/api/careers/{save}").status_code == 200
    assert list(repository._parsed) == saves[-repository.CACHED_SAVES:]
    client.get(f"/api/careers/{saves[0]}")
    assert list(repository._parsed)[-1] == saves[0] and len(repository._parsed) == repository.CACHED_SAVES


def test_the_saved_careers_list_follows_a_job_change(client):
    from sqlmodel import Session

    from app import db, repository

    save = client.post("/api/careers", json={"team": "T1", "seed": 3}).json()["id"]
    with Session(db.get_engine()) as session:
        row, career = repository.load_save(session, save, fresh=True)
        career.team = "GEN"  # what jobs.take does when the manager accepts an offer
        repository.store(session, row, career)
    listed = next(s for s in client.get("/api/careers").json() if s["id"] == save)
    assert listed["team"]["id"] == "GEN"
