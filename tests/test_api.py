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


def test_unknown_team_is_rejected(client):
    assert client.post("/api/careers", json={"team": "NOPE"}).status_code == 400


def test_a_career_from_draft_to_a_played_game(client):
    career = client.post("/api/careers", json={"manager": "Martin", "team": "G2", "seed": 99}).json()
    save = career["id"]
    assert career["phase"] == "draft" and career["draft"]["my_turn"]

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

    for _ in range(20):
        career = act(client, save, {"type": "advance"})["career"]
        if career["live"]:
            break
    assert career["live"]

    live = client.get(f"/api/careers/{save}/live").json()
    assert live["phase"] == "lineup"
    act(client, save, {"type": "start_champ_select"})
    live = client.get(f"/api/careers/{save}/live").json()
    turn = live["select"]["turn"]
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
