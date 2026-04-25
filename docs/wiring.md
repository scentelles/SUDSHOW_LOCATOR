# Câblage — SudShow Locator

## Belt Pack Performer (Tag + ESP32)

### Connexion BU-01 Tag → ESP32

Utilisez 4 fils Dupont femelle-femelle, ~10cm :

| BU-01 Tag (broche) | ESP32 DevKit | Couleur |
|---------------------|-------------|----------|
| **U1TX**            | **GPIO16** (RX2) | Vert    |
| **U1RX**            | **GPIO17** (TX2) | Jaune   |
| **V5**              | **VIN** (5V)     | Rouge   |
| **GND**             | **GND**          | Noir    |

> **Important** :
> - TX → RX et RX → TX (croisé)
> - Câbles courts (~10cm) pour éviter les interférences
> - Les pins U1TX/U1RX sont sur le côté droit du BU-01 (voir sérigraphie)

### Alimentation du belt pack

**Option recommandée — Petite power bank USB :**
- Branchez la power bank USB → ESP32 (port micro-USB)
- L'ESP32 fournit le 5V au BU-01 via le pin VIN → V5
- Autonomie : ~6-8h avec power bank 5000mAh

**Montage pratique :**
```
┌───────────────────────────┐
│  Sacoche ceinture / poche  │
│                           │
│  ┌───────┐  4 fils ┌─────┐│
│  │ BU-01 │◄─────►│ESP32││
│  │ Tag   │        │     ││
│  └───────┘        └──┬──┘│
│                     │ USB │
│             ┌───────┴──┐ │
│             │PowerBank│ │
│             └─────────┘ │
└───────────────────────────┘
```

---

## Anchors (3× BU-01 autonomes)

Chaque anchor est simplement :
- BU-01 alimenté via USB (power bank)
- Aucune autre connexion nécessaire
- Configuré en mode Anchor (persistant après redémarrage)

### Configuration initiale (déjà faite ✅)

Via le dongle USB-TTL + script quick_config.py :
```
python tools/quick_config.py COM7 anchor 0   # Module marqué A0
python tools/quick_config.py COM7 anchor 1   # Module marqué A1
python tools/quick_config.py COM7 anchor 2   # Module marqué A2
python tools/quick_config.py COM7 tag         # Module marqué TAG
```

Vérification après reset : `device:anchor ID:X` ou `device:TAG ID:0`

### Données UART confirmées (test du 25/04/2026)

Format de sortie du Tag (115200 baud) :
```
an0:5.77m
an1:1.35m
an2:5.95m
```
- 1 cycle complet (3 anchors) toutes les ~1.3 secondes
- Précision mesurée : ±2-3 cm
- Commande de démarrage : `AT+switchdis=1`

---

## Schéma global

```
                      SCÈNE
    ┌─────────────────────────────────────────┐
    │                                         │
    │   🔵 Anchor 0              🔵 Anchor 1 │
    │   (BU-01 + PowerBank)      (BU-01 + PB)│
    │                                         │
    │         🔴 Performer                    │
    │         (BU-01 Tag + ESP32)             │
    │         Belt Pack                       │
    │                                         │
    │              🔵 Anchor 2                │
    │              (BU-01 + PB)               │
    │                                         │
    └─────────────────────────────────────────┘
                                    │
                              WiFi UDP │
                                    ▼
                            🖥️ PC Régie
                          (Python → Telnet)
                                │
                          Telnet :30000
                                ▼
                          🏛️ GrandMA2 onPC
                                │
                            DMX
                                ▼
                    💡💡💡💡 Lyres (barre)
```
