"""Protocole BLE des lampes Arcadia Reptile LumenIZE (ProT5 / JungleDawn LED Bar).

Reversé depuis com.qh.app.arcadia 1.1.4 (classe BleOperateTool).

Toutes les trames font 16 octets, sauf l'écriture de programme (152).
  octet[0]  = famille de commande
  octet[1]  = opération  (0x0F = requête hôte, 0xF0/0xF1/0xF2 = ordres, 0xF0 = réponse lampe)
  octet[-1] = famille << 4   (toujours, y compris sur la trame de 152)
"""

SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
WRITE_UUID   = "0000fff2-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID  = "0000fff1-0000-1000-8000-00805f9b34fb"

DEFAULT_PASSWORD = "1234"
MAX_SLOTS = 48

MODES = [
    "Light Cycle 1", "Light Cycle 2",
    "Custom Mode 1", "Custom Mode 2", "Custom Mode 3", "Custom Mode 4", "Custom Mode 5",
]

# R.array.customs_br : % affiché (0-100) -> % réellement envoyé à la lampe.
# 0 reste 0, mais 1 % vaut déjà 45 % : en dessous le driver LED ne démarre pas proprement
# (c'est le « safe start » décrit dans la notice).
GAMMA = [
    0, 45, 46, 46, 47, 47, 48, 48, 49, 49, 50, 51, 51, 52, 52, 53, 53, 54, 54, 55,
    56, 56, 57, 57, 58, 58, 59, 59, 60, 60, 61, 62, 62, 63, 63, 64, 64, 65, 65, 66,
    67, 67, 68, 68, 69, 69, 70, 70, 71, 71, 72, 73, 73, 74, 74, 75, 75, 76, 76, 77,
    78, 78, 79, 79, 80, 80, 81, 81, 82, 82, 83, 84, 84, 85, 85, 86, 86, 87, 87, 88,
    89, 89, 90, 90, 91, 91, 92, 92, 93, 93, 94, 95, 95, 96, 96, 97, 97, 98, 98, 99, 100,
]


def to_wire(pct: int) -> int:
    """% affiché -> % transmis."""
    return GAMMA[max(0, min(100, int(pct)))]


def from_wire(raw: int) -> int:
    """% transmis -> % affiché (inverse de la table, au plus proche)."""
    if raw <= 0:
        return 0
    return min(range(1, 101), key=lambda i: abs(GAMMA[i] - raw))


def _frame(family: int, op: int, body: bytes = b"") -> bytearray:
    f = bytearray(16)
    f[0] = family
    f[1] = op
    f[2:2 + len(body)] = body
    f[15] = (family << 4) & 0xFF
    return f


def _pwd_digits(password: str) -> bytes:
    """« 1234 » -> b'\\x01\\x02\\x03\\x04 ». L'app exige exactement 4 chiffres."""
    p = (password or "").strip()
    if len(p) != 4 or not p.isdigit():
        raise ValueError("le mot de passe doit faire exactement 4 chiffres")
    return bytes(int(c) for c in p)


# ---------------------------------------------------------------- 0x01 horloge

def set_clock(now) -> bytearray:
    """01 0F — cale l'horloge interne. La lampe la réclame en envoyant 01 F0."""
    weekday = (now.weekday() + 1) % 7          # Java Calendar : 0 = dimanche
    y = now.year
    f = _frame(0x01, 0x0F)
    f[2] = y & 0xFF
    f[3] = (y >> 8) & 0xFF
    f[4] = weekday
    f[5] = now.month
    f[6] = now.day
    f[7] = now.hour
    f[8] = now.minute
    f[9] = now.second
    return f


# ------------------------------------------------- 0x02 état + contrôle direct

def query_status() -> bytearray:
    """02 0F — demande l'état. Réponse : 02 F0 <auto> <luminosité> <mode>."""
    return _frame(0x02, 0x0F)


def set_output(pct: int, mode: int, auto: bool) -> bytearray:
    """02 F1 — auto=True fait tourner le programme interne, auto=False donne la main
    au curseur. Le mode est renvoyé à chaque fois : ne jamais l'oublier, sinon la
    lampe bascule sur le mode 0."""
    return _frame(0x02, 0xF1, bytes([1 if auto else 0, to_wire(pct), mode & 0xFF]))


# ------------------------------------------------------------ 0x03 programmes

def query_schedule(mode: int) -> bytearray:
    """03 0F <mode> — réponse : 03 F0 <mode> <nb> puis <nb> triplets."""
    return _frame(0x03, 0x0F, bytes([mode & 0xFF]))


def write_schedule(mode: int, slots, edited_index: int = 0) -> bytearray:
    """03 F1 — écrit un programme complet. `slots` = [(heure, minute, %), ...],
    48 créneaux maximum. La trame fait 152 octets, d'où le MTU à 200."""
    slots = list(slots)
    if len(slots) > MAX_SLOTS:
        raise ValueError(f"{MAX_SLOTS} créneaux maximum")
    f = bytearray(152)
    f[0] = 0x03
    f[1] = 0xF1
    f[2] = mode & 0xFF
    f[3] = len(slots)
    for i in range(MAX_SLOTS):
        off = 4 + i * 3
        if i < len(slots):
            h, m, pct = slots[i]
            f[off] = (h & 0x7F) | 0x80        # bit 7 = créneau utilisé
            f[off + 1] = m & 0xFF
            f[off + 2] = to_wire(pct)
    f[148] = 0x0F
    f[149] = edited_index & 0xFF
    f[150] = 0
    f[151] = 0x30
    return f


# ------------------------------------------------------------ 0x04 test pleine puissance

def full_power(on: bool) -> bytearray:
    """04 F0 / 04 0F — dans l'app c'est un appui maintenu : F0 à l'appui, 0F au relâché.
    Sert à identifier physiquement une lampe."""
    return _frame(0x04, 0xF0 if on else 0x0F)


# --------------------------------------------------------------- 0x05 login

def login(password: str = DEFAULT_PASSWORD) -> bytearray:
    """05 F0 — à envoyer dès que les notifications sont actives."""
    return _frame(0x05, 0xF0, b"\x00" + _pwd_digits(password))


def verify_password(password: str) -> bytearray:
    """05 F1 — renvoyé après un refus de login."""
    return _frame(0x05, 0xF1, b"\x00" + _pwd_digits(password))


# ------------------------------------------------- 0x06 gestion du mot de passe

def set_password(password: str) -> bytearray:
    """06 F1 — change le mot de passe et active la protection."""
    f = _frame(0x06, 0xF1, b"\x00" + _pwd_digits(password))
    f[7] = 1
    return f


def set_protection(enabled: bool) -> bytearray:
    """06 F2 — active/désactive la demande de mot de passe."""
    f = _frame(0x06, 0xF2)
    f[7] = 1 if enabled else 0
    return f


# ------------------------------------------------------------------ décodage

def parse(data: bytes) -> dict:
    """Décode une notification reçue sur fff1."""
    d = bytes(data)
    if len(d) < 2:
        return {"type": "?", "raw": d.hex()}
    fam, op = d[0], d[1]

    if fam == 0x01 and op == 0xF0:
        return {"type": "clock_request",
                "note": "la lampe réclame l'heure — répondre par set_clock()"}

    if fam == 0x02 and op == 0xF0:
        out = {"type": "status",
               "auto": d[2] != 0,
               "brightness_raw": d[3],
               "brightness": from_wire(d[3]),
               "mode": d[4],
               "mode_name": MODES[d[4]] if d[4] < len(MODES) else f"? ({d[4]})"}
        # Les octets 5-14 portent quelque chose que l'app n'exploite pas et que
        # je n'ai pas identifié (ils changent d'une interrogation à l'autre).
        # Exposés bruts plutôt qu'interprétés à tort.
        if len(d) >= 15:
            out["extra"] = d[5:15].hex()
        return out

    if fam == 0x03 and op == 0xF0:
        mode, count, slots = d[2], d[3], []
        i = 4
        while i + 2 < len(d) and len(slots) < count:
            if d[i] & 0x80:
                slots.append({"hour": d[i] & 0x7F, "minute": d[i + 1],
                              "brightness": from_wire(d[i + 2]),
                              "brightness_raw": d[i + 2]})
            i += 3
        return {"type": "schedule", "mode": mode,
                "mode_name": MODES[mode] if mode < len(MODES) else f"? ({mode})",
                "count": count, "slots": slots}

    if fam == 0x05:
        return {"type": "login",
                "accepted": len(d) > 2 and d[2] == 1,
                "password": "".join(str(b) for b in d[3:7]) if len(d) > 6 else None,
                "protected": d[7] == 1 if (op == 0xF0 and len(d) > 7) else None}

    if fam == 0x06:
        return {"type": "password_change", "accepted": len(d) > 2 and d[2] == 1}

    return {"type": "unknown", "family": fam, "op": op, "raw": d.hex()}
