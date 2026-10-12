"""Build app/data/champions.json from Data Dragon and the hand-tagged table below.

    python -m scripts.build_champions

Data Dragon gives every champion's id (used for images and to match gol.gg) and display name.
The table adds what the simulation needs and Riot does not publish: which roles a champion is
played in, when it is strongest and what damage it deals. Tags started from riftlike's list."""

import json
from pathlib import Path

import httpx

PATCH = "16.20.1"
OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "champions.json"
ROLE_LETTER = {"T": "TOP", "J": "JNG", "M": "MID", "B": "BOT", "S": "SUP"}
FOCUS = {"E": "early", "M": "mid", "L": "late"}

# name | roles (first one is the main role) | focus | damage (AD, AP, MX = mixed) | class
TABLE = """
Aatrox|T|E|AD|Fighter
Ahri|M|M|AP|Mage
Akali|MT|M|AP|Assassin
Akshan|M|E|AD|Marksman
Alistar|S|E|AP|Tank
Ambessa|T|M|AD|Fighter
Amumu|J|M|AP|Tank
Anivia|M|L|AP|Mage
Annie|MS|M|AP|Mage
Aphelios|B|L|AD|Marksman
Ashe|BS|M|AD|Marksman
Aurelion Sol|M|L|AP|Mage
Aurora|MT|M|AP|Mage
Azir|M|L|AP|Mage
Bard|S|M|AP|Enchanter
Bel'Veth|J|L|AD|Fighter
Blitzcrank|S|E|AP|Tank
Brand|JS|M|AP|Mage
Braum|S|M|AP|Tank
Briar|J|E|AD|Fighter
Caitlyn|B|M|AD|Marksman
Camille|TS|M|AD|Fighter
Cassiopeia|MT|L|AP|Mage
Cho'Gath|T|L|AP|Tank
Corki|M|L|MX|Marksman
Darius|T|E|AD|Fighter
Diana|JM|M|AP|Assassin
Dr. Mundo|T|L|AD|Tank
Draven|B|E|AD|Marksman
Ekko|JM|M|AP|Assassin
Elise|J|E|AP|Assassin
Evelynn|J|M|AP|Assassin
Ezreal|B|M|AD|Marksman
Fiddlesticks|J|M|AP|Mage
Fiora|T|L|AD|Fighter
Fizz|M|M|AP|Assassin
Galio|MS|M|AP|Tank
Gangplank|T|L|AD|Fighter
Garen|T|M|AD|Fighter
Gnar|T|M|AD|Fighter
Gragas|TJS|M|AP|Tank
Graves|J|M|AD|Marksman
Gwen|TJ|L|AP|Fighter
Hecarim|J|M|AD|Fighter
Heimerdinger|MTS|M|AP|Mage
Hwei|MS|M|AP|Mage
Illaoi|T|M|AD|Fighter
Irelia|TM|M|AD|Fighter
Ivern|J|L|AP|Enchanter
Janna|S|L|AP|Enchanter
Jarvan IV|J|E|AD|Tank
Jax|TJ|L|AD|Fighter
Jayce|TM|E|AD|Fighter
Jhin|B|M|AD|Marksman
Jinx|B|L|AD|Marksman
K'Sante|T|M|AD|Tank
Kai'Sa|B|L|MX|Marksman
Kalista|B|E|AD|Marksman
Karma|SM|M|AP|Enchanter
Karthus|J|L|AP|Mage
Kassadin|M|L|AP|Assassin
Katarina|M|M|AP|Assassin
Kayle|T|L|AP|Fighter
Kayn|J|M|AD|Assassin
Kennen|T|M|AP|Mage
Kha'Zix|J|M|AD|Assassin
Kindred|J|L|AD|Marksman
Kled|T|E|AD|Fighter
Kog'Maw|B|L|MX|Marksman
LeBlanc|M|E|AP|Assassin
Lee Sin|J|E|AD|Fighter
Leona|S|E|AP|Tank
Lillia|J|M|AP|Mage
Lissandra|M|M|AP|Mage
Locke|MJ|E|AD|Assassin
Lucian|BM|E|AD|Marksman
Lulu|S|L|AP|Enchanter
Lux|SM|M|AP|Mage
Malphite|TS|M|AP|Tank
Malzahar|M|L|AP|Mage
Maokai|JS|M|AP|Tank
Master Yi|J|L|AD|Assassin
Mel|MS|M|AP|Mage
Milio|S|L|AP|Enchanter
Miss Fortune|B|M|AD|Marksman
Mordekaiser|T|M|AP|Fighter
Morgana|SM|M|AP|Mage
Naafiri|M|E|AD|Assassin
Nami|S|M|AP|Enchanter
Nasus|T|L|AD|Fighter
Nautilus|S|E|AP|Tank
Neeko|MS|M|AP|Mage
Nidalee|J|E|AP|Assassin
Nilah|B|M|AD|Fighter
Nocturne|J|M|AD|Assassin
Nunu & Willump|J|M|AP|Tank
Olaf|TJ|E|AD|Fighter
Orianna|M|L|AP|Mage
Ornn|T|L|AP|Tank
Pantheon|JTMS|E|AD|Fighter
Poppy|TJS|M|AD|Tank
Pyke|S|E|AD|Assassin
Qiyana|MJ|E|AD|Assassin
Quinn|T|E|AD|Marksman
Rakan|S|M|AP|Enchanter
Rammus|J|M|AP|Tank
Rek'Sai|J|E|AD|Fighter
Rell|S|E|AP|Tank
Renata Glasc|S|M|AP|Enchanter
Renekton|T|E|AD|Fighter
Rengar|JT|E|AD|Assassin
Riven|T|E|AD|Fighter
Rumble|TMJ|M|AP|Mage
Ryze|MT|L|AP|Mage
Samira|B|E|AD|Marksman
Sejuani|J|M|AP|Tank
Senna|BS|L|AD|Marksman
Seraphine|SB|M|AP|Mage
Sett|TS|E|AD|Fighter
Shaco|JS|E|AD|Assassin
Shen|TS|M|AD|Tank
Shyvana|J|L|MX|Fighter
Singed|T|M|AP|Tank
Sion|T|L|AD|Tank
Sivir|B|M|AD|Marksman
Skarner|JT|M|AD|Tank
Smolder|BMT|L|AD|Marksman
Sona|S|L|AP|Enchanter
Soraka|S|L|AP|Enchanter
Swain|MSB|M|AP|Mage
Sylas|MJ|M|AP|Fighter
Syndra|M|M|AP|Mage
Tahm Kench|TS|M|AP|Tank
Taliyah|MJ|M|AP|Mage
Talon|MJ|E|AD|Assassin
Taric|S|M|AP|Tank
Teemo|T|M|AP|Mage
Thresh|S|M|AP|Tank
Tristana|BM|E|AD|Marksman
Trundle|JT|M|AD|Fighter
Tryndamere|T|L|AD|Fighter
Twisted Fate|M|M|AP|Mage
Twitch|B|L|AD|Marksman
Udyr|J|M|MX|Fighter
Urgot|T|M|AD|Fighter
Varus|B|M|AD|Marksman
Vayne|BT|L|AD|Marksman
Veigar|MB|L|AP|Mage
Vel'Koz|SMB|M|AP|Mage
Vex|M|M|AP|Mage
Vi|J|E|AD|Fighter
Viego|J|M|AD|Assassin
Viktor|M|L|AP|Mage
Vladimir|MT|L|AP|Mage
Volibear|TJ|E|AD|Fighter
Warwick|J|E|AD|Fighter
Wukong|JT|M|AD|Fighter
Xayah|B|M|AD|Marksman
Xerath|SM|M|AP|Mage
Xin Zhao|J|E|AD|Fighter
Yasuo|MTB|M|AD|Fighter
Yone|MT|L|AD|Fighter
Yorick|T|M|AD|Fighter
Yunara|B|L|AD|Marksman
Yuumi|S|L|AP|Enchanter
Zaahen|TJ|M|AD|Fighter
Zac|TJ|M|AP|Tank
Zed|M|E|AD|Assassin
Zeri|B|L|AD|Marksman
Ziggs|MB|L|AP|Mage
Zilean|S|L|AP|Enchanter
Zoe|M|M|AP|Mage
Zyra|S|M|AP|Mage
"""


def main() -> None:
    url = f"https://ddragon.leagueoflegends.com/cdn/{PATCH}/data/en_US/champion.json"
    dragon = httpx.get(url, timeout=60).json()["data"]
    by_name = {c["name"]: c for c in dragon.values()}
    champions = []
    for line in TABLE.strip().splitlines():
        name, roles, focus, damage, cls = line.split("|")
        info = by_name.pop(name)
        champions.append({
            "id": info["id"],
            "name": name,
            "roles": [ROLE_LETTER[r] for r in roles],
            "focus": FOCUS[focus],
            "damage": damage,
            "class": cls,
        })
    if by_name:
        raise SystemExit(f"untagged champions in Data Dragon {PATCH}: {sorted(by_name)}")
    # One champion per line keeps the file short and its diffs readable.
    lines = ",\n".join("  " + json.dumps(c) for c in champions)
    OUT.write_text(f'{{\n "patch": "{PATCH}",\n "champions": [\n{lines}\n ]\n}}\n', encoding="utf-8")
    print(f"{len(champions)} champions written")


if __name__ == "__main__":
    main()
