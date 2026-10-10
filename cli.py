#!/usr/bin/env python3
"""lumenize — pilote une lampe Arcadia LumenIZE en Bluetooth LE."""
import argparse, asyncio, datetime, sys
import calendar_rules as C
import lamp as L
import protocol as P


def _fmt_status(s):
    src = "programme interne" if s["auto"] else "curseur manuel"
    return (f"luminosité {s['brightness']}%  (brut {s['brightness_raw']})\n"
            f"pilotage   {src}\n"
            f"mode       {s['mode']} — {s['mode_name']}")


def _fmt_schedule(s):
    if not s["slots"]:
        return f"mode {s['mode']} ({s['mode_name']}) : aucun créneau"
    out = [f"mode {s['mode']} ({s['mode_name']}) — {len(s['slots'])} créneaux"]
    for sl in sorted(s["slots"], key=lambda x: (x["hour"], x["minute"])):
        bar = "█" * round(sl["brightness"] / 5)
        out.append(f"  {sl['hour']:02d}:{sl['minute']:02d}  {sl['brightness']:3d}%  {bar}")
    return "\n".join(out)


def _parse_slots(items):
    slots = []
    for it in items:
        try:
            when, pct = it.split("=")
            h, m = when.split(":")
            slots.append((int(h), int(m), int(pct)))
        except ValueError:
            raise SystemExit(f"créneau invalide : « {it} » (attendu HH:MM=pourcentage)")
    return slots


async def run(args):
    cfg = L._load()

    if args.command == "scan":
        found = await L.discover(args.timeout)
        if not found:
            return print("aucune lampe LumenIZE détectée "
                         "(sous tension ? app du téléphone fermée ?)")
        for d in found:
            known = cfg["devices"].get(d["mac"], {})
            d["alias"] = known.get("alias")          # un scan ne perd pas l'alias
            cfg["devices"][d["mac"]] = d
            print(f"{L.label(d):<16} MAC {d['mac']}  RSSI {d['rssi']:>4}  {d['address']}")
        cfg["default"] = cfg.get("default") or found[0]["mac"]
        L._save(cfg)
        print(f"\nenregistré dans {L.CONFIG}")
        return

    if args.command == "devices":
        for mac, d in cfg["devices"].items():
            mark = "*" if mac == cfg.get("default") else " "
            print(f"{mark} {L.label(d):<16} MAC {mac}  ({d.get('name')})")
        return

    if args.command == "rename":
        dev = L.resolve(cfg, args.device)
        before = L.label(dev)
        dev["alias"] = args.newname
        L._save(cfg)
        print(f"« {before} » → « {args.newname} »  (MAC {dev['mac']})")
        print("Alias local, comme dans l'app : la lampe continue d'annoncer "
              f"« {dev.get('name')} » en Bluetooth.")
        return

    if args.address:
        address = args.address
    else:
        dev = L.resolve(cfg, args.device)
        address = dev["address"]

    async with L.Lamp(address, args.password, args.verbose) as lamp:
        if args.command == "status":
            print(_fmt_status(await lamp.status()))

        elif args.command == "brightness":
            print(_fmt_status(await lamp.set_brightness(args.value)))

        elif args.command == "off":
            print(_fmt_status(await lamp.set_brightness(0)))

        elif args.command == "on":
            print(_fmt_status(await lamp.set_brightness(args.value)))

        elif args.command == "auto":
            print(_fmt_status(await lamp.set_auto(args.state == "on")))

        elif args.command == "mode":
            print(_fmt_status(await lamp.set_mode(args.value)))

        elif args.command == "schedule":
            if args.slots:
                print(_fmt_schedule(await lamp.set_schedule(args.mode, _parse_slots(args.slots))))
            elif args.mode is not None:
                print(_fmt_schedule(await lamp.get_schedule(args.mode)))
            else:
                for m in range(len(P.MODES)):
                    try:
                        print(_fmt_schedule(await lamp.get_schedule(m)))
                    except asyncio.TimeoutError:
                        print(f"mode {m} ({P.MODES[m]}) : pas de réponse")
                    print()

        elif args.command == "test":
            await lamp.full_power_test(args.seconds)
            print("impulsion pleine puissance envoyée")

        elif args.command == "clock":
            await lamp.sync_clock()
            print("horloge interne recalée")

        elif args.command == "calendar":
            cfg = C.load()
            wanted, weekend = C.wanted_mode(cfg)
            st = await lamp.status()
            day = C.DAYS[datetime.datetime.now().weekday()]
            kind = "week-end" if weekend else "semaine"
            print(f"{day} → horaire {kind} → mode {wanted} ({P.MODES[wanted]})")
            print(f"mode actuel : {st['mode']} ({st['mode_name']})")

            if not cfg["enabled"]:
                print("bascule désactivée (calendar.json)")
            elif st["mode"] == wanted:
                print("déjà sur le bon mode, rien à faire")
                C.log(f"ok {day} mode {wanted}")
            elif args.dry_run:
                print(f"il faudrait basculer sur le mode {wanted} (essai à blanc)")
            else:
                st = await lamp.set_mode(wanted)
                ok = st["mode"] == wanted
                print(f"bascule → mode {st['mode']} ({st['mode_name']}) "
                      f"{'✓' if ok else '✗ ECHEC'}")
                C.log(f"{'bascule' if ok else 'ECHEC'} {day} -> mode {wanted}")

        elif args.command == "watch":
            print("écoute des notifications (Ctrl-C pour sortir)")
            while True:
                print(await lamp._events.get())


def main():
    p = argparse.ArgumentParser(prog="lumenize", description=__doc__)
    p.add_argument("--address", help="UUID CoreBluetooth (sinon la lampe enregistrée)")
    p.add_argument("--device", help="nom, alias ou MAC d'une lampe déjà scannée")
    p.add_argument("--password", default=P.DEFAULT_PASSWORD, help="4 chiffres (défaut 1234)")
    p.add_argument("-v", "--verbose", action="store_true", help="montre les trames brutes")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("scan", help="cherche les lampes et les enregistre")
    s.add_argument("--timeout", type=float, default=12.0)

    sub.add_parser("devices", help="liste les lampes connues")

    s = sub.add_parser("rename", help="donne un nom local à une lampe")
    s.add_argument("newname")

    sub.add_parser("status", help="état actuel")

    s = sub.add_parser("brightness", help="luminosité 0-100 (passe en manuel)")
    s.add_argument("value", type=int)

    s = sub.add_parser("on", help="allume (manuel)")
    s.add_argument("value", type=int, nargs="?", default=100)

    sub.add_parser("off", help="éteint (0 %%, la lampe reste alimentée)")

    s = sub.add_parser("auto", help="rend la main au programme interne")
    s.add_argument("state", choices=["on", "off"])

    s = sub.add_parser("mode", help="change de mode (0-6)")
    s.add_argument("value", type=int, choices=range(len(P.MODES)))

    s = sub.add_parser("schedule", help="lit ou écrit un programme horaire")
    s.add_argument("mode", type=int, nargs="?", choices=range(len(P.MODES)))
    s.add_argument("slots", nargs="*", metavar="HH:MM=%",
                   help="ex. 06:00=0 11:00=100 15:00=100 19:00=0")

    s = sub.add_parser("test", help="impulsion pleine puissance (identifier la lampe)")
    s.add_argument("--seconds", type=float, default=1.5)

    sub.add_parser("clock", help="recale l'horloge interne")

    s = sub.add_parser("calendar", help="applique le mode du jour (semaine / week-end)")
    s.add_argument("--dry-run", action="store_true", help="dit ce qu'il ferait, sans agir")
    sub.add_parser("watch", help="affiche les notifications en direct")

    args = p.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
    except (RuntimeError, asyncio.TimeoutError) as e:
        sys.exit(f"erreur : {e}")


if __name__ == "__main__":
    main()
