# lumenize

Pilotage en ligne de commande des lampes **Arcadia Reptile LumenIZE** (ProT5, JungleDawn LED Bar)
depuis un Mac, sans l'app officielle (notée 1,6/5 sur l'App Store).

Protocole reversé depuis l'APK Android `com.qh.app.arcadia` 1.1.4 (classe `BleOperateTool`),
puis vérifié sur une JungleDawn LED Bar 18W (`RARLJ1`).

## Installation

macOS, Python 3.10+ et le Bluetooth activé.

    git clone https://github.com/bini74/lumenize.git
    cd lumenize
    ./install.sh          # venv + bleak, commande ~/.local/bin/lumenize

Au premier lancement, macOS demande l'autorisation Bluetooth pour le terminal.
Fermer l'app LumenIZE du téléphone : tant qu'elle est connectée, la lampe est invisible.

Documentation complète dans le [wiki](https://github.com/bini74/lumenize/wiki).

## Usage

    lumenize scan                 # trouve les lampes et les mémorise
    lumenize devices              # liste les lampes connues
    lumenize rename terrarium     # alias local (voir plus bas)
    lumenize status               # luminosité, mode, auto/manuel
    lumenize brightness 40        # passe en manuel et fixe la luminosité
    lumenize off                  # 0 % (la lampe reste sous tension)
    lumenize auto on              # rend la main au programme interne
    lumenize mode 3               # change de mode (0-6)
    lumenize schedule             # lit les programmes de tous les modes
    lumenize schedule 2 06:00=0 11:00=100 15:00=100 19:00=0
    lumenize test                 # impulsion pleine puissance (identifier la lampe)
    lumenize clock                # recale l'horloge interne
    lumenize calendar             # applique le mode du jour (semaine / week-end)
    lumenize calendar --dry-run   # dit ce qu'il ferait, sans agir
    lumenize -v status            # affiche les trames brutes

Options : `--device <alias|nom|MAC>`, `--address <uuid>`, `--password <4 chiffres>`.

Les lampes sont mémorisées dans `~/.config/lumenize/devices.json`, indexées par MAC —
seul identifiant stable : l'UUID CoreBluetooth est propre à chaque Mac, et toutes les
lampes du même modèle annoncent le même nom.

## Protocole

Service `fff0`, écriture sans réponse sur `fff2`, notifications sur `fff1`.
Trames de 16 octets (152 pour l'écriture d'un programme, d'où le MTU à 200).

    octet[0]  famille
    octet[1]  opération — 0x0F requête hôte, 0xF0/0xF1/0xF2 ordres, 0xF0 en réponse
    octet[-1] famille << 4

| Trame | Sens | Rôle |
|---|---|---|
| `01 0F` année(2) jour_sem mois jour h m s | → | cale l'horloge |
| `01 F0` | ← | la lampe réclame l'heure |
| `02 0F` | → | demande l'état |
| `02 F0 <auto> <lum> <mode>` | ← | état |
| `02 F1 <auto> <lum> <mode>` | → | luminosité / bascule auto-manuel |
| `03 0F <mode>` | → | demande le programme d'un mode |
| `03 F0 <mode> <n>` + n×(h\|0x80, m, %) | ← | programme |
| `03 F1 <mode> <n>` + 48×(h\|0x80, m, %) + `0F <idx> 00 30` | → | écrit un programme (152 o) |
| `04 F0` / `04 0F` | → | pleine puissance : appui / relâché |
| `05 F0 00 p p p p` | → | login (mot de passe par défaut `1234`) |
| `05 F0 <ok> p p p p <protégé>` | ← | réponse de login |
| `06 F1 00 p p p p 01` | → | change le mot de passe |
| `06 F2 00 …… <on>` | → | active/désactive la protection |

### Pièges

- **Toujours renvoyer le mode** dans `02 F1` : à zéro, la lampe bascule sur le mode 0.
  (L'intégration Home Assistant existante a ce défaut.)
- **Écrire un programme active ce mode.** Restaurer le mode voulu derrière, comme fait l'app.
- **Courbe de gamma** : l'échelle affichée 1-100 % est remappée sur 45-100 % à l'envoi
  (`R.array.customs_br`). 0 reste 0. En dessous de 45 le driver LED ne démarre pas
  proprement — c'est le « safe start » de la notice.
- **Modes 0 et 1** (*Light Cycle 1* et *2*) sont câblés dans le firmware : ils ne répondent
  pas aux lectures de programme. Seuls les modes 2-6 (*Custom Mode 1-5*) sont éditables.
- **Il n'y a pas de vrai extinction** : « éteindre » revient à descendre à 0 %.
- macOS ne fournit jamais la MAC d'un périphérique BLE. Elle est récupérée dans les
  manufacturer data (company ID `0x5148`), où la lampe la recopie en clair.
- La lampe cesse d'émettre son advertising dès qu'une app y est connectée.
- **Elle n'annonce aucun service UUID** : son advertising ne contient que les manufacturer
  data. `FFF0` n'apparaît qu'après connexion, dans la table GATT. Un scan filtré sur le
  service ne la trouvera donc jamais — filtrer sur le company ID `0x5148`.
- **Le nom d'une lampe ne peut pas être changé.** Le « renommage » de l'app officielle
  écrit juste `SharedPreferences[MAC] = nom` (`o1/f.java`) : aucune trame BLE, et le GATT
  n'expose aucune caractéristique de nom. `lumenize rename` fait la même chose de son côté ;
  les deux alias sont indépendants.

## Semaine / week-end

**La lampe ne sait pas distinguer les jours.** Son format de programme n'a aucune
notion de jour de la semaine : chaque mode est un cycle de 24 h répété à l'identique.
Le seul octet de jour du protocole sert à régler l'horloge, et aucun créneau ne s'y
réfère. L'application officielle ne le permet pas davantage.

Le contournement consiste à garder deux cycles dans deux modes, et à choisir lequel
est actif selon le jour :

| | |
|---|---|
| Perso 1 (mode 2) | cycle de semaine |
| Perso 3 (mode 4) | cycle de week-end |

`lumenize calendar` compare le mode attendu au mode réellement actif et corrige s'il
y a lieu. Il est **correctif et non déclencheur** : une exécution manquée se rattrape
au passage suivant.

Réglages dans `~/.config/lumenize/calendar.json` (`weekend_days` suit la convention
Python : lundi = 0, dimanche = 6). Journal dans `calendar.log`.

Pour l'automatiser, une tâche launchd horaire suffit (`~/Library/LaunchAgents/…plist`
avec `ProgramArguments` = `~/.local/bin/lumenize calendar` et `StartInterval` = 3600).
Le Mac doit être allumé et à portée Bluetooth de la lampe.
