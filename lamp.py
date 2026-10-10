"""Client BLE pour les lampes Arcadia LumenIZE."""
import asyncio, json, os, datetime
from bleak import BleakClient, BleakScanner
import protocol as P

CONFIG = os.path.expanduser("~/.config/lumenize/devices.json")


def _load():
    """Les lampes sont indexées par MAC, comme le fait l'app officielle : c'est le
    seul identifiant stable (l'UUID CoreBluetooth est propre à chaque Mac, et le nom
    annoncé est le même « Arcadia1 » sur toutes les lampes du même modèle)."""
    try:
        with open(CONFIG) as f:
            cfg = json.load(f)
    except Exception:
        return {"devices": {}, "default": None}
    if "devices" in cfg:
        return cfg
    # Ancien format, indexé par nom annoncé.
    devices = {v["mac"]: v for k, v in cfg.items() if isinstance(v, dict) and v.get("mac")}
    default = next((v["mac"] for k, v in cfg.items()
                    if isinstance(v, dict) and k == cfg.get("_default")), None)
    return {"devices": devices, "default": default}


def _save(d):
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(CONFIG, "w") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)


def resolve(cfg, wanted=None):
    """Trouve une lampe par alias, par nom annoncé ou par MAC."""
    devices = cfg.get("devices", {})
    if not devices:
        raise SystemExit("aucune lampe connue — lancer « lumenize scan » d'abord")
    if wanted is None:
        mac = cfg.get("default") or next(iter(devices))
        return devices[mac]
    w = wanted.strip().lower()
    for mac, dev in devices.items():
        if w in (mac.lower(), (dev.get("alias") or "").lower(), (dev.get("name") or "").lower()):
            return dev
    raise SystemExit(f"lampe inconnue : « {wanted} »")


def label(dev):
    return dev.get("alias") or dev.get("name") or dev.get("mac")


async def discover(timeout=12.0):
    """Repère les lampes LumenIZE. macOS ne donne pas la MAC : on la lit dans
    les manufacturer data (company ID 0x5148), où la lampe la recopie en clair."""
    found = {}

    def cb(dev, adv):
        mfg = (adv.manufacturer_data or {}).get(0x5148)
        name = adv.local_name or dev.name or ""
        if mfg is None and not name.startswith("Arcadia"):
            return
        mac = ":".join(f"{b:02X}" for b in mfg[2:8]) if mfg and len(mfg) >= 8 else None
        found[dev.address] = {"address": dev.address, "name": name,
                              "mac": mac, "rssi": adv.rssi}

    scanner = BleakScanner(detection_callback=cb)
    await scanner.start()
    await asyncio.sleep(timeout)
    await scanner.stop()
    return list(found.values())


class Lamp:
    def __init__(self, address, password=P.DEFAULT_PASSWORD, verbose=False):
        self.address = address
        self.password = password
        self.verbose = verbose
        self._client = None
        self._events = asyncio.Queue()
        self.state = {}

    # -- plomberie ---------------------------------------------------------
    def _on_notify(self, _sender, data):
        msg = P.parse(data)
        if self.verbose:
            print(f"  <- {bytes(data).hex()}  {msg}")
        if msg["type"] == "status":
            self.state = msg
        # La lampe réclame l'heure : on la lui donne sans attendre.
        if msg["type"] == "clock_request":
            asyncio.create_task(self.send(P.set_clock(datetime.datetime.now())))
        self._events.put_nowait(msg)

    async def send(self, frame):
        if self.verbose:
            print(f"  -> {bytes(frame).hex()}")
        await self._client.write_gatt_char(P.WRITE_UUID, bytes(frame), response=False)

    async def wait_for(self, kind, timeout=6.0):
        """Attend une notification d'un type donné, en ignorant les autres."""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise asyncio.TimeoutError(f"pas de réponse « {kind} »")
            msg = await asyncio.wait_for(self._events.get(), remaining)
            if msg["type"] == kind:
                return msg

    # -- cycle de vie ------------------------------------------------------
    async def __aenter__(self):
        dev = await BleakScanner.find_device_by_address(self.address, timeout=20.0)
        if not dev:
            raise RuntimeError(f"lampe introuvable ({self.address}) — allumée ? "
                               "app du téléphone fermée ?")
        self._client = BleakClient(dev, timeout=25.0)
        await self._client.connect()
        await self._client.start_notify(P.NOTIFY_UUID, self._on_notify)
        await self.send(P.login(self.password))
        try:
            msg = await self.wait_for("login", timeout=5.0)
            if not msg["accepted"]:
                raise RuntimeError(f"mot de passe refusé ({self.password})")
        except asyncio.TimeoutError:
            pass  # certaines lampes ne répondent pas au login quand la protection est off
        await self.send(P.set_clock(datetime.datetime.now()))
        await asyncio.sleep(0.2)
        return self

    async def __aexit__(self, *exc):
        try:
            await self._client.stop_notify(P.NOTIFY_UUID)
        except Exception:
            pass
        await self._client.disconnect()

    # -- opérations --------------------------------------------------------
    async def status(self):
        await self.send(P.query_status())
        return await self.wait_for("status")

    async def _mode(self):
        return (self.state or await self.status())["mode"]

    async def set_brightness(self, pct):
        """Passe en manuel et fixe la luminosité."""
        await self.send(P.set_output(pct, await self._mode(), auto=False))
        await asyncio.sleep(0.3)
        return await self.status()

    async def set_auto(self, enabled, pct=None):
        """Rend la main au programme interne (True) ou au curseur (False)."""
        if pct is None:
            pct = (self.state or await self.status())["brightness"]
        await self.send(P.set_output(pct, await self._mode(), auto=enabled))
        await asyncio.sleep(0.3)
        return await self.status()

    async def set_mode(self, mode):
        st = self.state or await self.status()
        await self.send(P.set_output(st["brightness"], mode, auto=st["auto"]))
        await asyncio.sleep(0.3)
        return await self.status()

    async def get_schedule(self, mode):
        await self.send(P.query_schedule(mode))
        return await self.wait_for("schedule")

    async def set_schedule(self, mode, slots):
        """Écrire un programme fait basculer la lampe sur ce mode : on restaure
        le mode actif derrière, comme le fait l'app."""
        previous = (self.state or await self.status())["mode"]
        await self.send(P.write_schedule(mode, slots))
        await asyncio.sleep(0.5)
        result = await self.get_schedule(mode)
        if previous != mode:
            st = self.state
            await self.send(P.set_output(st["brightness"], previous, st["auto"]))
            await asyncio.sleep(0.3)
            await self.status()
        return result

    async def full_power_test(self, seconds=1.5):
        await self.send(P.full_power(True))
        await asyncio.sleep(seconds)
        await self.send(P.full_power(False))

    async def sync_clock(self):
        await self.send(P.set_clock(datetime.datetime.now()))
