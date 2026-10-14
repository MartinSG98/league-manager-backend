"""The transfer window: buying and selling players under contract, free agency, the AI clubs'
market, and what players think about all of it.

The window is the off-season only: from the day after the Worlds final to WINDOW_CLOSES
(January 16th, the eve of the next season). Contracts that run out with the season end on
FREE_AGENCY (December 1st); until then a club can still extend its own players, after that they
are free agents anyone can sign without a fee.

A player under contract costs a transfer fee. Their market value comes from the salary their
rating and reputation command, the seasons left on the contract and the room they have to grow.
The selling club asks more than the market value for a starter or for its only player in a role,
less for a listed or a bench player, and never sells its franchise player; only the manager's can go,
and only to a bid of at least twice his market value (FRANCHISE_PRICE). A bid at the asking
fee is accepted, one within three quarters of it gets a counter, a lower one is turned down.

Once the clubs agree, the player has to agree personal terms (see contracts.py). Players weigh
the buying club's reputation against their own (see interest): a star does not move to a club
far below their level, and a reluctant player wants more money.

AI clubs shop too. Each day of the window a club may sign a free agent for a hole in its lineup,
or bid for an upgrade: from another AI club, which answers at once, or from the manager, whose
answer the bid waits four days for. Turning down a bid from a bigger club upsets the player, who
asks to talk (see talk). A promise to let them go is remembered: turning down the next big bid
breaks it.

When the window closes every club must field five: AI clubs and the manager's assistant sign the
best free agents they can afford for any empty role."""

from datetime import date, timedelta
from math import ceil

from app.game import contracts, manager, reputation, roster
from app.game import staff as staffing
from app.game.catalog import ROLES, Catalog
from app.game.errors import IllegalAction
from app.game.ratings import asking_salary
from app.game.rng import Rng
from app.game.state import Career, Contract, Conversation, InboxMessage, TeamState, TransferOffer

FREE_AGENCY = (12, 1)
WINDOW_CLOSES = (1, 16)  # of the next year, the day before the first split starts
OFFER_DAYS = 4  # how long an AI club waits for the manager's answer
TALK_DAYS = 7  # how long a player waits to be heard
AI_MOVE_CHANCE = 0.045  # a day, per AI club
HOLE_GAP = 15  # a starter this far below the rest of the five is a hole the club fills first, every day
COUNTER_FROM = 0.75  # a bid this close to the asking fee gets a counter
MAX_BID_ROUNDS = 3
TALKS_OFF_DAYS = 14  # how long a club that ended the talks takes no bid for the player
AI_CUSHION = 0.3  # the share of its bank an AI club keeps after a deal
AI_RAISE = 1.12  # how much an AI club adds when the manager asks for more
FRANCHISE_PRICE = 2.0  # an AI club bids for the manager's franchise player only at this many times his value
FRANCHISE_LIMIT = 3.0  # and raises such a bid up to this many times it
FRANCHISE_INTEREST = 0.25  # how often a club that could afford him tries
FRANCHISE_CHOICE_DAYS = 14  # the manager's time to name a new franchise player
SELL_LIMIT = 1.35  # the most an AI club pays over market value


def _message(career: Career, kind: str, subject: str, body: str, offer: int | None = None,
             conversation: int | None = None) -> InboxMessage:
    msg = InboxMessage(id=career.next_message, day=career.day, kind=kind, subject=subject, body=body,  # type: ignore[arg-type]
                       offer=offer, conversation=conversation)
    career.inbox.append(msg)
    career.next_message += 1
    return msg


# ---------- the window ----------


def window_open(career: Career) -> bool:
    return career.phase == "offseason"


def free_agency_day(career: Career) -> date:
    return date(career.season, *FREE_AGENCY)


def closing_day(career: Career) -> date:
    return date(career.season + 1, *WINDOW_CLOSES)


# ---------- what a player is worth and what they think ----------


def seasons_left(career: Career, pid: str) -> int:
    contract = career.players[pid].contract
    if contract is None:
        return 0
    now = career.season + 1 if career.phase == "offseason" else career.season
    return max(0, contract.until - now + 1)


def market_value(cat: Catalog, career: Career, pid: str) -> int:
    """Thousands of USD."""
    p = cat.players[pid]
    rating = roster.overall(cat, career, pid)
    team = career.players[pid].team
    region = cat.teams[team].region if team in cat.teams else cat.leagues[p.league].region
    salary = asking_salary(rating, p.reputation, region)
    years = seasons_left(career, pid)
    value = salary * (0.5 + 0.55 * years) * (1 + max(0, p.potential - rating) / 30)
    return int(max(10, round(value / 5) * 5))


def asking_fee(cat: Catalog, career: Career, pid: str) -> int | None:
    """What the club that holds the player wants for them; None when they are not for sale."""
    state = career.players[pid]
    team = career.teams.get(state.team or "")
    if team is None:
        return None
    if team.franchise == pid:
        return None
    fee = market_value(cat, career, pid)
    role = cat.players[pid].role
    starter = team.lineup.get(role) == pid
    fee *= 1.3 if starter else 0.85
    if sum(1 for p in team.roster if cat.players[p].role == role) == 1:
        fee *= 1.25
    if pid in team.listed or state.unsettled:
        fee *= 0.8
    return int(round(fee / 5) * 5)


def home_region(cat: Catalog, career: Career, pid: str) -> str | None:
    """The region a player sees clubs from: their club's, else that of the league they last played in."""
    team = career.players[pid].team
    if team in cat.teams:
        return cat.teams[team].region
    league = cat.leagues.get(cat.players[pid].league)
    return league.region if league else None


def interest(cat: Catalog, career: Career, pid: str, team_id: str) -> tuple[str, str]:
    """("keen" | "open" | "reluctant" | "refuses", why). Players measure the club's reputation
    against their own standing: their reputation, or that of the club they play for less 12,
    whichever is higher, so nobody at a top club steps far down. A club of the player's own
    region is seen on the region's scale, any other on the world's (see reputation.compared). An
    unsettled player is easier to tempt."""
    p = cat.players[pid]
    state = career.players[pid]
    if state.team == team_id:
        return "keen", "Already at the club"
    current = state.team if state.team in career.teams else None
    club, now = reputation.compared(cat, career, team_id, current, home_region(cat, career, pid))
    standing = max(p.reputation, now - 12)
    gap = standing - (club - 10) - (8 if state.unsettled else 0)
    stars = reputation.stars(club)
    if gap > 20:
        reason = "their reputation is far above it" if p.reputation >= now - 12 else "they would not leave a bigger club for it"
        return "refuses", f"{p.name} does not want to join a {stars:g}-star club; {reason}"
    if gap > 8:
        return "reluctant", f"{p.name} would need convincing (and more money) to join a {stars:g}-star club"
    if club >= now + 8:
        return "keen", f"{p.name} would love a move to a bigger club"
    return "open", f"{p.name} is open to joining"


def reluctance_premium(level: str) -> float:
    return 1.15 if level == "reluctant" else 1.0


# ---------- the manager buying ----------


def moved(career: Career) -> set[str]:
    """Players who already changed clubs in this window; nobody sells them on straight away."""
    return {m["player"] for m in career.transfers}


def reserved(career: Career) -> int:
    """Fees the manager has agreed and not paid yet: they wait on personal terms."""
    return sum(o.fee for o in career.offers if o.buyer == career.team and o.status == "agreed")


def free_cash(career: Career) -> int:
    """What the bank holds beyond the fees already agreed."""
    return career.teams[career.team].cash - reserved(career)


def agreed(career: Career, pid: str) -> TransferOffer | None:
    """A fee agreed for the manager to buy this player, waiting on personal terms."""
    return next((o for o in career.offers if o.player == pid and o.buyer == career.team and o.status == "agreed"), None)


def spoken_for(career: Career, pid: str) -> bool:
    """A bid for the player is open or its fee agreed: no other club moves for him meanwhile."""
    return any(o.player == pid and o.status in ("open", "agreed") for o in career.offers)


def call_off(cat: Catalog, career: Career, pid: str, seller: str) -> None:
    """The player left the club that was selling him, so the bids for him there fall through."""
    name = cat.players[pid].name
    for o in career.offers:
        if o.player != pid or o.seller != seller or o.status not in ("open", "agreed"):
            continue
        what = f"the {o.fee}k fee you agreed" if o.status == "agreed" else f"your {o.fee}k bid"
        o.status = "collapsed"
        o.note = f"{name} left {cat.teams[seller].name}."
        if o.buyer == career.team:
            _message(career, "transfer", f"Deal off: {name}", f"{name} has left {cat.teams[seller].name}, so {what} is off.")


def stale_deals(cat: Catalog, career: Career) -> bool:
    """Call off agreed fees for players who have left the selling club since. Saves from before
    call_off kept them. Returns True when there were any."""
    stale = [o for o in career.offers if o.status == "agreed" and career.players[o.player].team != o.seller]
    for o in stale:
        call_off(cat, career, o.player, o.seller)
    return bool(stale)


def _new_offer(career: Career, pid: str, buyer: str, seller: str, fee: int, days: int) -> TransferOffer:
    offer = TransferOffer(id=career.next_offer, player=pid, buyer=buyer, seller=seller, fee=fee, day=career.day,
                          expires=career.day + timedelta(days=days))
    career.next_offer += 1
    career.offers.append(offer)
    return offer


def _last_bid(career: Career, pid: str) -> TransferOffer | None:
    """The manager's latest bid for the player in this window (the last one closed on January 16th)."""
    opened = date(career.season, *WINDOW_CLOSES)
    return next((o for o in reversed(career.offers)
                 if o.player == pid and o.buyer == career.team and o.day > opened), None)


def _talks_ended(offer: TransferOffer | None) -> bool:
    return offer is not None and offer.status == "rejected" and offer.rounds >= MAX_BID_ROUNDS


def check_bid(cat: Catalog, career: Career, pid: str, fee: int | None = None) -> str | None:
    if not window_open(career):
        return "Transfers happen in the off-season window, after Worlds"
    if career.board.meeting:
        return "Meet the board first"
    if pid not in cat.players:
        return "Unknown player"
    state = career.players[pid]
    name = cat.players[pid].name
    if state.team is None:
        return f"{name} is a free agent: offer a contract instead"
    if state.team == career.team:
        return f"{name} already plays for you"
    if career.teams[state.team].franchise == pid:
        return f"{cat.teams[state.team].name} will not sell their franchise player"
    if pid in moved(career):
        return f"{name} only just joined {cat.teams[state.team].name}"
    if agreed(career, pid):
        return f"The fee for {name} is agreed: talk contract terms with them"
    last = _last_bid(career, pid)
    if _talks_ended(last) and career.day < last.expires and last.seller == state.team:
        return f"{cat.teams[state.team].name} ended the talks for {name}: no new bid before {last.expires:%d %B}"
    team = career.teams[career.team]
    if len(team.roster) >= contracts.MAX_ROSTER:
        return f"Your roster is full ({contracts.MAX_ROSTER} players)"
    level, why = interest(cat, career, pid, career.team)
    if level == "refuses":
        return why
    if team.cash < 0:
        return f"The club is {-team.cash}k in debt: the board pays for no transfers until the bank is back above zero"
    free = free_cash(career)
    if fee is not None and fee > free:
        held = reserved(career)
        return f"You have {free}k free in the bank" + (f" ({held}k is set aside for fees you agreed)" if held else "")
    return None


def bid(cat: Catalog, career: Career, pid: str, fee: int) -> TransferOffer:
    problem = check_bid(cat, career, pid, fee)
    if problem:
        raise IllegalAction(problem)
    if fee <= 0:
        raise IllegalAction("Bid a fee")
    seller = career.players[pid].team or ""
    offer = next((o for o in career.offers if o.player == pid and o.buyer == career.team and o.status == "open"), None)
    last = _last_bid(career, pid)
    if (offer is None and last is not None and last.status == "rejected" and last.seller == seller
            and not _talks_ended(last)):
        # A bid turned down does not start the talks over: every failed bid in the window counts.
        offer = last
        offer.status = "open"
        offer.expires = career.day + timedelta(days=OFFER_DAYS)
    if offer is None:
        offer = _new_offer(career, pid, career.team, seller, fee, OFFER_DAYS)
    offer.fee = fee
    offer.rounds += 1
    # What they settle for: a good negotiator gets something off the asking fee, a poor one pays it.
    ask = int(round((asking_fee(cat, career, pid) or 0) * min(1.0, manager.haggle(career)) / 5) * 5)
    seller_name = cat.teams[seller].name
    name = cat.players[pid].name
    if fee >= ask:
        offer.status = "agreed"
        offer.counter = None
        offer.expires = closing_day(career)
        offer.note = f"{seller_name} accept {fee}k for {name}. Now agree personal terms with the player."
    elif fee >= ask * COUNTER_FROM and offer.rounds < MAX_BID_ROUNDS:
        offer.counter = ask
        offer.note = f"{seller_name} want {ask}k for {name}."
    else:
        offer.status = "rejected"
        offer.counter = None
        if offer.rounds < MAX_BID_ROUNDS:
            offer.note = f"{seller_name} turn the bid down."
        else:
            offer.expires = career.day + timedelta(days=TALKS_OFF_DAYS)
            offer.note = (f"{seller_name} are tired of haggling and end the talks: no new bid for {name} "
                          f"before {offer.expires:%d %B}.")
    return offer


def withdraw(career: Career, offer_id: int) -> None:
    offer = _offer(career, offer_id)
    if offer.buyer != career.team or offer.status not in ("open", "agreed"):
        raise IllegalAction("That bid is no longer open")
    offer.status = "withdrawn"
    offer.note = "You withdrew the bid."


def complete_purchase(cat: Catalog, career: Career, pid: str) -> TransferOffer | None:
    """Personal terms are agreed (contracts._sign): pay the fee and take the player from the seller."""
    offer = agreed(career, pid)
    if offer is None:
        return None
    if career.players[pid].team != offer.seller:
        call_off(cat, career, pid, offer.seller)
        return None
    offer.status = "completed"  # before the move, which calls off every other bid for him there
    offer.note = f"Completed for {offer.fee}k."
    _move(cat, career, pid, offer.seller, offer.buyer, offer.fee)
    return offer


# ---------- the manager selling ----------


def _offer(career: Career, offer_id: int) -> TransferOffer:
    offer = next((o for o in career.offers if o.id == offer_id), None)
    if offer is None:
        raise IllegalAction("No such offer")
    return offer


def respond(cat: Catalog, career: Career, offer_id: int, response: str, rng: Rng) -> TransferOffer:
    offer = _offer(career, offer_id)
    if offer.seller != career.team or offer.status != "open":
        raise IllegalAction("That offer is no longer open")
    if not window_open(career):
        raise IllegalAction("The transfer window is closed")
    pid = offer.player
    name = cat.players[pid].name
    buyer = cat.teams[offer.buyer].name
    if response == "accept":
        state = career.players[pid]
        offer.status = "completed"
        offer.note = f"{name} joins {buyer} for {offer.fee}k."
        club = career.teams[offer.buyer]
        _spend(career, club, _fund(career, club, _salary_for(cat, career, pid, club), offer.fee, _room(career, club)))
        star = career.teams[career.team].franchise == pid
        _move(cat, career, pid, career.team, offer.buyer, offer.fee)
        state.promise = None
        _message(career, "transfer", f"{name} sold to {buyer}", f"{offer.note} The fee is in the bank.")
        if star:
            vacate_franchise(cat, career, career.teams[career.team], f"{name} has been sold")
        return offer
    if response == "negotiate":
        star = career.teams[career.team].franchise == pid
        ceiling = market_value(cat, career, pid) * (FRANCHISE_LIMIT if star else SELL_LIMIT)
        raised = int(round(offer.fee * AI_RAISE / 5) * 5)
        buyer_team = career.teams[offer.buyer]
        if offer.rounds >= 2 or raised > ceiling or raised > buyer_team.cash:
            offer.status = "withdrawn"
            offer.note = f"{buyer} will not go higher and walk away."
        else:
            offer.rounds += 1
            offer.fee = raised
            offer.expires = career.day + timedelta(days=OFFER_DAYS)
            offer.note = f"{buyer} raise their bid to {raised}k."
        return offer
    offer.status = "rejected"
    offer.note = f"You turned down {buyer}."
    _after_rejection(cat, career, offer)
    return offer


def _after_rejection(cat: Catalog, career: Career, offer: TransferOffer) -> None:
    """A player wanted by a bigger club, or one who was promised a move, wants a word."""
    pid = offer.player
    state = career.players[pid]
    theirs, mine = reputation.compared(cat, career, offer.buyer, career.team, cat.teams[career.team].region)
    big = theirs >= mine + 3
    if state.promise is not None and state.promise <= career.season and big:
        state.promise = None
        state.unsettled = True
        state.morale = max(0, state.morale - 30)
        _talk(cat, career, pid, "broken_promise", offer.buyer)
        return
    ambitious = cat.players[pid].reputation >= mine - 5
    if big or (ambitious and theirs >= mine):
        state.morale = max(0, state.morale - 8)
        _talk(cat, career, pid, "rejected_bid", offer.buyer)


def set_listed(cat: Catalog, career: Career, pid: str, listed: bool) -> None:
    team = career.teams[career.team]
    if pid not in team.roster:
        raise IllegalAction("That player is not on your roster")
    if pid == team.franchise and listed:
        raise IllegalAction("The board will not sell the franchise player")
    if listed and pid not in team.listed:
        team.listed.append(pid)
    if not listed and pid in team.listed:
        team.listed.remove(pid)


# ---------- conversations ----------


def _talk(cat: Catalog, career: Career, pid: str, topic: str, team: str | None) -> Conversation:
    talk = Conversation(id=career.next_offer, player=pid, topic=topic, team=team, day=career.day,  # type: ignore[arg-type]
                        expires=career.day + timedelta(days=TALK_DAYS))
    career.next_offer += 1
    career.conversations.append(talk)
    name = cat.players[pid].name
    club = cat.teams[team].name if team else "another club"
    if topic == "broken_promise":
        subject = f"{name} feels betrayed"
        body = (f"You promised {name} a move if a big club came in. {club} did, and you said no. "
                f"{name} wants to talk, and is not happy.")
    else:
        subject = f"{name} wants to talk about {club}'s offer"
        body = (f"{name} heard that you turned down {club}. A move there would have meant a lot, and "
                f"{name} wants to hear why. Answer within {TALK_DAYS} days.")
    _message(career, "player", subject, body, conversation=talk.id)
    return talk


TALK_CHOICES = {
    "vital": "You are vital to this team. I am building around you.",
    "promise": "If a club like that comes in again next off-season, I will let you go.",
    "final": "The decision is final. You are under contract here.",
}


def talk(cat: Catalog, career: Career, talk_id: int, choice: str, rng: Rng) -> Conversation:
    conv = next((c for c in career.conversations if c.id == talk_id), None)
    if conv is None or conv.resolved:
        raise IllegalAction("That conversation is over")
    if choice == "promise" and conv.topic == "broken_promise":
        raise IllegalAction("A second promise would not be believed")
    _resolve(cat, career, conv, choice, rng)
    return conv


def _resolve(cat: Catalog, career: Career, conv: Conversation, choice: str, rng: Rng) -> None:
    state = career.players[conv.player]
    name = cat.players[conv.player].name
    team = career.teams.get(career.team)
    starter = team is not None and conv.player in team.lineup.values()
    conv.resolved = True
    if choice == "vital":
        odds = 0.5 + (reputation.manager_in(career, career.region) - 60) / 100 + (0.15 if starter else -0.1)
        odds += 0.02 * (manager.own(career, "man_management") - manager.NEUTRAL)
        odds -= 0.25 if conv.topic == "broken_promise" else 0.0
        if rng.chance(max(0.1, min(0.9, odds))):
            state.morale = max(state.morale, 60)
            state.unsettled = False
            conv.outcome = f"{name} accepts it and gets back to work."
        else:
            state.morale = max(0, state.morale - 12)
            state.unsettled = True
            conv.outcome = f"{name} does not believe you and wants to leave."
    elif choice == "promise":
        state.morale = max(state.morale, 68)
        state.unsettled = False
        state.promise = career.season + 1
        conv.outcome = f"{name} is happy with that. Remember the promise next off-season."
    else:
        state.morale = max(0, state.morale - 18)
        state.unsettled = state.unsettled or rng.chance(0.6)
        conv.outcome = (f"{name} is angry and asks to be sold." if state.unsettled
                        else f"{name} accepts it, without a smile.")
    _message(career, "player", f"Talk with {name}", f'You: "{TALK_CHOICES[choice]}"\n{conv.outcome}')


# ---------- moving players ----------


def _move(cat: Catalog, career: Career, pid: str, seller: str, buyer: str, fee: int) -> None:
    """Fee from buyer to seller and the player from one roster to the other. The manager's own
    signings get their contract from contracts._sign; AI buyers sign at the asking salary."""
    state = career.players[pid]
    out, into = career.teams[seller], career.teams[buyer]
    out.cash += fee
    into.cash -= fee
    _leave(cat, career, out, pid)
    state.unsettled = False
    state.training.attribute = None
    state.training.champion = None
    if buyer != career.team:
        _join(cat, career, into, pid)
    career.transfers.append({"day": career.day.isoformat(), "player": pid, "from": seller, "to": buyer, "fee": fee})


def _leave(cat: Catalog, career: Career, team: TeamState, pid: str) -> None:
    if pid in team.roster:
        team.roster.remove(pid)
    if pid in team.listed:
        team.listed.remove(pid)
    role = cat.players[pid].role
    if team.lineup.get(role) == pid:
        backup = max((p for p in team.roster if cat.players[p].role == role),
                     key=lambda p: roster.overall(cat, career, p), default=None)
        if backup:
            team.lineup[role] = backup
        else:
            del team.lineup[role]
    career.players[pid].team = None
    career.players[pid].contract = None
    call_off(cat, career, pid, team.id)


def _join(cat: Catalog, career: Career, team: TeamState, pid: str, years: int = 2) -> None:
    state = career.players[pid]
    p = cat.players[pid]
    region = cat.teams[team.id].region
    salary = asking_salary(roster.overall(cat, career, pid), p.reputation, region)
    first = career.season + 1 if career.phase == "offseason" else career.season
    state.team = team.id
    state.contract = Contract(salary=salary, until=first + years - 1)
    state.morale = max(state.morale, 72)
    team.roster.append(pid)
    current = team.lineup.get(p.role)
    if current is None or roster.overall(cat, career, current) < roster.overall(cat, career, pid):
        team.lineup[p.role] = pid


# ---------- the AI market ----------


def _room(career: Career, team: TeamState) -> int:
    return team.budget - roster.payroll(career, team, season=career.season + 1)


def _fund(career: Career, team: TeamState, salary: int, fee: int, room: int) -> int | None:
    """How an AI club pays a salary and a fee, moving money between its salary budget and its bank
    as the manager's slider does (finances.move): the change to its salary budget, 0 when both fit as
    they are, or None when it cannot pay. A salary beyond the room raises the budget, paid from the
    bank; a fee beyond what the bank spares comes out of wage budget the club will not use. The club
    keeps AI_CUSHION of its bank, and moves nothing into the budget while in debt. `room` is _room."""
    from app.game import finances  # here: finances needs this module

    rate = finances.weeks_left(career) / finances.WEEKS
    cushion = AI_CUSHION * max(0, team.cash)
    if salary > room:
        rise = ceil((salary - room) / finances.STEP) * finances.STEP
        return rise if team.cash > 0 and team.cash - fee - rise * rate >= cushion else None
    if team.cash - fee >= cushion:
        return 0
    spare = team.budget - contracts.committed(career, team) - salary
    cut = ceil((cushion - (team.cash - fee)) / rate / finances.STEP) * finances.STEP
    return -cut if cut <= spare else None


def _spend(career: Career, team: TeamState, change: int | None) -> None:
    """Move what _fund worked out between the club's salary budget and its bank."""
    from app.game import finances

    if change:
        finances.move(career, team, team.budget + change)


def _weakest_role(cat: Catalog, career: Career, team: TeamState) -> tuple[str, int]:
    """A role with nobody in it, or the starter with the lowest rating."""
    for role in ROLES:
        if role not in team.lineup:
            return role, 0
    role = min(ROLES, key=lambda r: roster.overall(cat, career, team.lineup[r]))
    return role, roster.overall(cat, career, team.lineup[role])


def _free_agents(cat: Catalog, career: Career, role: str, region: str | None = None) -> list[str]:
    out = []
    for p in cat.players.values():
        state = career.players[p.id]
        if p.role != role or state.team is not None or state.retired:
            continue
        if region is not None and cat.leagues[p.league].region != region:
            continue
        out.append(p.id)
    return out


def _salary_for(cat: Catalog, career: Career, pid: str, team: TeamState) -> int:
    return asking_salary(roster.overall(cat, career, pid), cat.players[pid].reputation, cat.teams[team.id].region)


def _sign_free_agent(cat: Catalog, career: Career, team: TeamState, role: str, need: int, force: bool = False,
                     record: bool = True) -> str | None:
    """The best free agent better than `need` the club can pay, from its own region if there is
    one there and from anywhere if not; with `force`, the best it can pay at all, or the cheapest
    one there is. `record` keeps the move in the window's list."""
    region = cat.teams[team.id].region
    room = _room(career, team)
    ai = team.id != career.team  # the manager's money moves only by their own hand

    def affordable(pid: str) -> bool:
        salary = _salary_for(cat, career, pid, team)
        return _fund(career, team, salary, 0, room) is not None if ai else salary <= room

    def candidates(pool: list[str]) -> list[str]:
        return [p for p in pool if affordable(p) and interest(cat, career, p, team.id)[0] != "refuses"]

    home = _free_agents(cat, career, role, region)
    pool = home or _free_agents(cat, career, role)
    fits = candidates(pool)
    better = [p for p in fits if roster.overall(cat, career, p) > need]
    if not better and home:
        # Nobody better at home: the club looks abroad.
        abroad = candidates([p for p in _free_agents(cat, career, role) if p not in set(home)])
        better = [p for p in abroad if roster.overall(cat, career, p) > need]
    choice = max(better, key=lambda p: roster.overall(cat, career, p), default=None)
    if choice is None and force:
        choice = (max(fits, key=lambda p: roster.overall(cat, career, p), default=None)
                  or min(pool, key=lambda p: _salary_for(cat, career, p, team), default=None))
    if choice is None:
        return None
    if ai:  # the forced cheapest one, when nobody fits, is signed over the budget as before
        _spend(career, team, _fund(career, team, _salary_for(cat, career, choice, team), 0, room))
    _join(cat, career, team, choice, years=1 if roster.overall(cat, career, choice) < need + 3 else 2)
    if record:
        career.transfers.append({"day": career.day.isoformat(), "player": choice, "from": None, "to": team.id, "fee": 0})
    return choice


def hole(cat: Catalog, career: Career, team: TeamState) -> bool:
    """Whether a club's five has a hole: an empty role, or a starter HOLE_GAP below the other four."""
    if len(team.lineup) < len(ROLES):
        return True
    ratings = {r: roster.overall(cat, career, p) for r, p in team.lineup.items()}
    weakest = min(ratings, key=lambda r: ratings[r])
    rest = [v for r, v in ratings.items() if r != weakest]
    return ratings[weakest] < sum(rest) / len(rest) - HOLE_GAP


def fill_holes(cat: Catalog, career: Career) -> None:
    """Mondays in the season: an AI club with a hole in its five signs a better free agent, if one
    will come and it can pay him. Clubs cannot buy players under contract until the window."""
    for team in career.teams.values():
        if team.id == career.team and not career.board.sacked:
            continue
        if not hole(cat, career, team):
            continue
        role, current = _weakest_role(cat, career, team)
        pid = _sign_free_agent(cat, career, team, role, current + 2, record=False)
        if pid:
            _news(cat, career, pid, None, team.id, 0)


def daily(cat: Catalog, career: Career, rng: Rng) -> None:
    """One day of the window."""
    if career.day == free_agency_day(career):
        open_free_agency(cat, career)
    for offer in career.offers:
        if offer.status == "open" and career.day > offer.expires:
            offer.status = "expired"
            offer.note = "Nobody answered in time."
    for conv in career.conversations:
        if not conv.resolved and career.day > conv.expires:
            _resolve(cat, career, conv, "final", rng)
    if career.day >= closing_day(career):
        return
    teams = [t for t in career.teams.values() if t.id != career.team or career.board.sacked]
    made_offer = False
    for team in rng.shuffle(teams):
        if not hole(cat, career, team) and not rng.chance(AI_MOVE_CHANCE):
            continue
        made_offer = _ai_move(cat, career, team, rng, allow_offer=not made_offer) or made_offer


# ---------- the franchise player ----------


def franchise_price(cat: Catalog, career: Career, pid: str) -> int:
    """The least an AI club bids for the manager's franchise player."""
    return int(round(market_value(cat, career, pid) * FRANCHISE_PRICE / 5) * 5)


def best_player(cat: Catalog, career: Career, team: TeamState) -> str | None:
    return max(team.roster, key=lambda p: (roster.overall(cat, career, p), cat.players[p].reputation), default=None)


def vacate_franchise(cat: Catalog, career: Career, team: TeamState, why: str) -> None:
    """The franchise player is gone. The manager names the next one, or the board does after
    FRANCHISE_CHOICE_DAYS; an AI club names its best player at once."""
    if team.id != career.team or career.board.sacked:
        team.franchise = best_player(cat, career, team)
        return
    team.franchise = None
    career.franchise_choice = career.day + timedelta(days=FRANCHISE_CHOICE_DAYS)
    _message(career, "player", "Name a new franchise player",
             f"{why}. Choose the new face of the club on a player's page (Make franchise player) by "
             f"{career.franchise_choice:%d %B}: not for sale unless a club bids twice his value, never released, and "
             "kept on when the contract runs out. If you do not, the board names your best player.")


def name_franchise(cat: Catalog, career: Career, pid: str) -> None:
    """The manager names the club's franchise player while the seat is empty."""
    team = career.teams[career.team]
    if team.franchise is not None or career.franchise_choice is None:
        raise IllegalAction("The club already has its franchise player")
    if pid not in team.roster:
        raise IllegalAction("Only one of your players can be the franchise player")
    team.franchise = pid
    career.franchise_choice = None
    name = cat.players[pid].name
    _message(career, "player", f"{name} is the new franchise player",
             f"{name} is the face of the club now: not for sale unless a club bids twice his value, never released, "
             "and kept on when the contract runs out.")


def franchise_daily(cat: Catalog, career: Career) -> None:
    """A club without a franchise player names its best one, unless the manager is still choosing."""
    for team in career.teams.values():
        if team.franchise is not None or not team.roster:
            continue
        mine = team.id == career.team
        if mine and career.franchise_choice is not None and career.day <= career.franchise_choice:
            continue
        team.franchise = best_player(cat, career, team)
        if mine and team.franchise:
            name = cat.players[team.franchise].name
            _message(career, "player", f"{name} is the new franchise player",
                     f"You did not name one, so the board makes {name}, your best player, the face of the club.")
    if career.franchise_choice is not None and career.teams[career.team].franchise is not None:
        career.franchise_choice = None


def _ai_move(cat: Catalog, career: Career, team: TeamState, rng: Rng, allow_offer: bool) -> bool:
    """One move by an AI club. Returns True when it bid for one of the manager's players."""
    role, current = _weakest_role(cat, career, team)
    if current == 0:
        return bool(_sign_free_agent(cat, career, team, role, 0, force=career.day >= free_agency_day(career)))
    if _sign_free_agent(cat, career, team, role, current + 2):
        return False
    room = _room(career, team)
    if team.cash <= 0:
        return False  # in debt the board pays for no transfers
    taken = moved(career)
    targets = []
    for p in cat.players.values():
        state = career.players[p.id]
        if p.role != role or state.team in (None, team.id) or state.team not in career.teams or p.id in taken:
            continue
        rating = roster.overall(cat, career, p.id)
        if rating < current + 4:
            continue
        seller = career.teams[state.team]
        own, theirs = reputation.compared(cat, career, team.id, seller.id, cat.teams[seller.id].region)
        if theirs > own + 5 and not state.unsettled:
            continue  # players do not step down for a club smaller than theirs
        star = state.team == career.team and seller.franchise == p.id
        if star and not rng.chance(FRANCHISE_INTEREST):
            continue  # a bid for a club's face is rare, and only for a fortune
        ask = franchise_price(cat, career, p.id) if star else asking_fee(cat, career, p.id)
        if ask is None or _fund(career, team, _salary_for(cat, career, p.id, team), ask, room) is None:
            continue
        if interest(cat, career, p.id, team.id)[0] == "refuses":
            continue
        if spoken_for(career, p.id):
            continue
        targets.append((rating - current - ask / 400, p.id, ask))
    if not targets:
        return False
    _, pid, ask = max(targets)
    seller = career.players[pid].team or ""
    if seller == career.team:
        if not allow_offer or career.board.sacked:
            return False
        value = market_value(cat, career, pid)
        star = career.teams[seller].franchise == pid
        if star:
            fee = int(round(value * (FRANCHISE_PRICE + rng.next() * 0.5) / 5) * 5)
            if fee > team.cash:
                return False  # never less than the fortune it takes
        else:
            fee = min(int(round(value * (0.9 + rng.next() * 0.3) / 5) * 5), team.cash)
        offer = _new_offer(career, pid, team.id, seller, fee, OFFER_DAYS)
        name = cat.players[pid].name
        offer.note = f"{cat.teams[team.id].name} bid {offer.fee}k for {name}."
        why = (" He is your franchise player: the board will sell him only for a bid like this, at least twice "
               "his value. Sell him and you name the next one.") if star else ""
        _message(career, "transfer", f"{cat.teams[team.id].name} bid {offer.fee}k for {name}",
                 f"{offer.note} Market value about {value}k.{why} Accept, turn it down or ask for more within "
                 f"{OFFER_DAYS} days.", offer=offer.id)
        return True
    fee = int(round(ask * (1.0 + rng.next() * 0.1) / 5) * 5)
    change = _fund(career, team, _salary_for(cat, career, pid, team), fee, room)
    if change is None:
        return False
    _spend(career, team, change)
    _move(cat, career, pid, seller, team.id, fee)
    _news(cat, career, pid, seller, team.id, fee)
    return False


def _news(cat: Catalog, career: Career, pid: str, seller: str | None, buyer: str, fee: int) -> None:
    """Moves the manager would care about: paid moves in their league, or the biggest names."""
    p = cat.players[pid]
    leagues = {cat.teams[buyer].league} | ({cat.teams[seller].league} if seller else set())
    if career.league not in leagues and p.reputation < 85:
        return
    origin = f"from {cat.teams[seller].name} for {fee}k" if seller else "as a free agent"
    _message(career, "news", f"{cat.teams[buyer].tag} sign {p.name}", f"{cat.teams[buyer].name} sign {p.name} ({p.role}) {origin}.")


# ---------- milestones of the window ----------


def open_window(cat: Catalog, career: Career) -> None:
    _message(career, "transfer", "The transfer window is open",
             f"Until {closing_day(career):%d %B}: buy and sell players under contract and sign free agents. "
             f"Contracts that end with the season run out on {free_agency_day(career):%d %B}; extend the players "
             "you want to keep before then.")


def open_free_agency(cat: Catalog, career: Career) -> None:
    """Contracts that ended with the season run out."""
    from app.game import hiring

    hiring.contracts_run_out(cat, career)
    gone = []
    for team in career.teams.values():
        for pid in list(team.roster):
            state = career.players[pid]
            if state.contract is None or state.contract.until > career.season:
                continue
            if pid == team.franchise:
                state.contract = Contract(salary=state.contract.salary, until=career.season + 3)
                continue
            _leave(cat, career, team, pid)
            if team.id == career.team:
                gone.append(cat.players[pid].name)
    body = "Players whose contracts ended are free agents now."
    if gone:
        body += f" Leaving your club: {', '.join(gone)}."
    _message(career, "transfer", "Free agency opens", body)


def close_window(cat: Catalog, career: Career) -> None:
    """Every club fields five before the season; open bids lapse."""
    for offer in career.offers:
        if offer.status in ("open", "agreed"):
            offer.status = "collapsed" if offer.status == "agreed" else "expired"
            offer.note = "The window closed."
    signed = []
    for team in career.teams.values():
        for role in ROLES:
            if role not in team.lineup:
                pid = _sign_free_agent(cat, career, team, role, 0, force=True)
                if pid and team.id == career.team:
                    signed.append(f"{cat.players[pid].name} ({role})")
        if team.id != career.team and hole(cat, career, team):
            # The last chance before the season: a starter far below the rest is replaced if anyone better is free.
            role, current = _weakest_role(cat, career, team)
            _sign_free_agent(cat, career, team, role, current + 2)
        for kind in ("coach", "analyst"):
            if getattr(team, kind) is None:
                _hire_staff(cat, career, team, kind)
    if signed:
        _message(career, "transfer", "Your assistant filled the empty roles",
                 f"The season starts and the lineup had holes, so the assistant signed {', '.join(signed)}.")
    career.offers = [o for o in career.offers if o.status in ("open", "agreed")]
    career.conversations = [c for c in career.conversations if not c.resolved]


def _hire_staff(cat: Catalog, career: Career, team: TeamState, kind: str) -> None:
    from app.game import draft

    pool = draft.available_staff(cat, career, team.league, kind)
    if not pool:
        return
    room = max(1, _room(career, team))
    person = max(pool, key=lambda s: s.overall - 60 * s.salary / max(room, 50))
    draft.hire(career, team, person)
    if kind == "coach":
        team.coach_since = career.day
    if team.id == career.team:
        _message(career, "staff", f"New {draft.STAFF_NAMES[kind]}: {person.name}",
                 f"The board hired {person.name} for {staffing.STAFF_YEARS} seasons at {person.salary}k a season.")


def view(cat: Catalog, career: Career) -> dict:
    """What the transfers screen shows."""
    from app.game import views

    def offer_row(o: TransferOffer) -> dict:
        return o.model_dump(mode="json") | {
            "player_row": views.player_row(cat, career, o.player),
            "buyer_team": views.team_ref(cat, o.buyer), "seller_team": views.team_ref(cat, o.seller),
            "value": market_value(cat, career, o.player),
        }

    team = career.teams[career.team]
    incoming = [offer_row(o) for o in career.offers if o.seller == career.team]
    outgoing = [offer_row(o) for o in career.offers if o.buyer == career.team]
    moves = []
    for move in reversed(career.transfers[-60:]):
        moves.append(move | {"player_row": views.player_row(cat, career, move["player"]),
                             "from_team": views.team_ref(cat, move["from"]), "to_team": views.team_ref(cat, move["to"])})
    return {
        "open": window_open(career),
        "closes": closing_day(career).isoformat() if window_open(career) else None,
        "free_agency": free_agency_day(career).isoformat() if window_open(career) else None,
        "cash": team.cash,
        "budget": team.budget,
        "room": _room(career, team) if window_open(career) else team.budget - roster.payroll(career, team),
        "incoming": sorted(incoming, key=lambda r: (r["status"] != "open", -r["id"])),
        "outgoing": sorted(outgoing, key=lambda r: (r["status"] not in ("open", "agreed"), -r["id"])),
        "listed": [views.player_row(cat, career, p) for p in team.listed if p in team.roster],
        "moves": moves,
        "conversations": [c.model_dump(mode="json") | {"player_row": views.player_row(cat, career, c.player),
                                                       "team_ref": views.team_ref(cat, c.team),
                                                       "choices": {k: v for k, v in TALK_CHOICES.items()
                                                                   if not (k == "promise" and c.topic == "broken_promise")}}
                          for c in reversed(career.conversations) if not c.resolved],
    }


def player_market(cat: Catalog, career: Career, pid: str) -> dict:
    """What the player page shows about buying or selling this player."""
    state = career.players[pid]
    level, why = interest(cat, career, pid, career.team)
    mine = state.team == career.team
    # The latest bid, whatever became of it, so the page can show the selling club's answer.
    offer = next((o for o in reversed(career.offers) if o.player == pid and o.buyer == career.team), None)
    return {
        "window_open": window_open(career),
        "value": market_value(cat, career, pid) if state.team else 0,
        "asking": None if mine else asking_fee(cat, career, pid),
        "interest": level,
        "interest_text": why,
        "listed": mine and pid in career.teams[career.team].listed,
        "bid_problem": None if mine or state.team is None else check_bid(cat, career, pid),
        "bid": offer.model_dump(mode="json") if offer else None,
        "promise": state.promise,
        "unsettled": state.unsettled,
    }
