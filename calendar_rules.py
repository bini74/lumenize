"""Bascule de mode selon le jour de la semaine.

La lampe ne sait pas faire ça toute seule : son format de programme n'a aucune
notion de jour, chaque mode est un cycle de 24 h répété à l'identique. On garde
donc deux modes distincts et on choisit lequel est actif.

Le principe est correctif plutôt que déclencheur : à chaque passage on compare le
mode attendu au mode réel et on corrige s'il y a lieu. Une exécution manquée
(Mac endormi, lampe hors de portée) se rattrape donc au passage suivant, au lieu
de laisser la lampe sur le mauvais cycle jusqu'à la semaine suivante.
"""
import datetime, json, os

CONFIG = os.path.expanduser("~/.config/lumenize/calendar.json")
LOG = os.path.expanduser("~/.config/lumenize/calendar.log")

DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

DEFAULT = {
    "enabled": True,
    "weekday_mode": 2,          # Perso 1
    "weekend_mode": 4,          # Perso 3
    "weekend_days": [5, 6],     # samedi, dimanche (lundi = 0)
}


def load():
    try:
        with open(CONFIG) as f:
            return {**DEFAULT, **json.load(f)}
    except Exception:
        return dict(DEFAULT)


def save(cfg):
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(CONFIG, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def wanted_mode(cfg, when=None):
    """Mode qui devrait être actif à cet instant."""
    when = when or datetime.datetime.now()
    weekend = when.weekday() in cfg["weekend_days"]
    return cfg["weekend_mode"] if weekend else cfg["weekday_mode"], weekend


def log(line):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f:
        f.write(f"{datetime.datetime.now().isoformat(timespec='seconds')}  {line}\n")
