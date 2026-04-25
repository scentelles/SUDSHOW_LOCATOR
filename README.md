# SudShow Locator

Système de suivi automatique de lumière sur scène par positionnement UWB (Ultra-Wideband).

## Principe

Un performer porte un module UWB (Tag) qui communique avec 3 modules fixes (Anchors) sur la scène. Un ESP32 calcule la position par trilatération et l'envoie via WiFi à un PC qui contrôle les lyres via GrandMA2.

## Architecture

```
BU-01 Anchors (×3, autonomes)  ←──UWB TWR──→  BU-01 Tag (performer)
                                                     │ UART
                                                ESP32 (WiFi)
                                                     │ UDP
                                                PC Python
                                                     │ Telnet
                                                GrandMA2 onPC
                                                     │ DMX
                                                💡 Lyres
```

## Structure

```
SUDSHOW_LOCATOR/
├── firmware/esp32_locator/    ← Firmware ESP32 (PlatformIO)
├── pc/                        ← Script Python + config
│   ├── locator_server.py      ← Serveur principal
│   └── config.json            ← Configuration (lyres, scène, réseau)
└── docs/                      ← Documentation
    └── wiring.md              ← Schéma de câblage
```

## Démarrage rapide

### 1. Préparer les modules BU-01

1. Installer le driver CH340 (voir [docs/wiring.md](docs/wiring.md))
2. Configurer 3 modules en Anchor : `AT+anchor_tag=1`
3. Configurer 1 module en Tag : `AT+anchor_tag=0`

### 2. Firmware ESP32

1. Ouvrir `firmware/esp32_locator` dans PlatformIO
2. Modifier `src/config.h` :
   - `WIFI_SSID` / `WIFI_PASS`
   - `UDP_TARGET_IP` (IP de votre PC)
   - Positions des anchors
3. Flasher sur l'ESP32

### 3. Script Python (PC)

1. Modifier `pc/config.json` :
   - Positions et IDs des fixtures GrandMA2
   - Credentials GrandMA2 Telnet
2. Activer Telnet dans GrandMA2 : `Setup > Console > Global Settings > Telnet = Login Enabled`
3. Lancer :
   ```bash
   cd pc
   python locator_server.py
   ```

### 4. Test sans hardware

Mode simulation (envoie des positions fictives) :
```bash
# Terminal 1 : serveur
python locator_server.py

# Terminal 2 : simulateur
python locator_server.py --simulate
```

Ou les deux ensemble :
```bash
python locator_server.py --sim-both
```

## Configuration

Tous les paramètres sont dans `pc/config.json`. Voir les commentaires pour les détails.

| Paramètre | Description | Défaut |
|-----------|-------------|--------|
| `stage.width` | Largeur scène (m) | 10.0 |
| `stage.depth` | Profondeur scène (m) | 5.0 |
| `fixtures[].height` | Hauteur de la lyre (m) | 4.0 |
| `tracking.target_height` | Hauteur du performer (m) | 1.7 |
| `tracking.smoothing_factor` | Lissage (0=max, 1=aucun) | 0.3 |
| `tracking.dead_zone_deg` | Zone morte (°) | 0.5 |

## Licence

Projet interne SudShow.
