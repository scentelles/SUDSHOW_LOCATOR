#pragma once
// =============================================================================
// SudShow Locator — Configuration
// =============================================================================
// Modifiez les paramètres ci-dessous selon votre installation.
// Toutes les distances sont en MÈTRES.
// =============================================================================

// =========================
//   RÉSEAU WiFi
// =========================
#define WIFI_SSID           "Wifi_Home"
#define WIFI_PASS           "060877040178"

// =========================
//   UDP — Envoi position
// =========================
// IP du PC qui exécute le script Python.
// Utilisez "255.255.255.255" pour broadcast sur tout le réseau.
#define UDP_TARGET_IP       "192.168.1.41"
#define UDP_TARGET_PORT     9000

// =========================
//   POSITIONS DES ANCHORS
// =========================
// Coordonnées (x, y) en mètres, dans le repère de la scène.
// Origine (0,0) = coin avant-gauche de la scène (face au public).
//
//   y ▲
//     │  (fond de scène)
//     │
//     │        🔵 A3 (5, 5)
//     │
//     │  🔵 A1 (0, 0)            🔵 A2 (10, 0)
//     └──────────────────────────► x
//         (avant-scène / public)
//
#define ANCHOR1_X           0.0f
#define ANCHOR1_Y           0.0f

#define ANCHOR2_X           10.0f
#define ANCHOR2_Y           0.0f

#define ANCHOR3_X           5.0f
#define ANCHOR3_Y           5.0f

// =========================
//   CALIBRATION UWB
// =========================
// Offset en mètres à déduire de la mesure brute pour compenser le délai des antennes (Antenna Delay).
// Exemple : Si l'Anchor 2 (qui correspond à l'index 1) affiche 1.00m au lieu de 0.20m, mettez 0.80f.
#define ANCHOR1_OFFSET      0.80f
#define ANCHOR2_OFFSET      0.80f
#define ANCHOR3_OFFSET      0.80f

// =========================
//   UART — BU-01 Tag
// =========================
// Broches série pour la connexion au module BU-01 Tag.
// Sur ESP32 : Serial2 utilise par défaut GPIO16 (RX) et GPIO17 (TX).
#define UWB_SERIAL_RX       16
#define UWB_SERIAL_TX       17
#define UWB_BAUD_RATE       115200

// =========================
//   FILTRAGE & MISE À JOUR
// =========================
// Le BU-01 fait ~1 cycle complet (3 anchors) toutes les 1.3s.
// L'envoi UDP se fait dès qu'un cycle complet est reçu.
// Ce paramètre limite la fréquence max d'envoi UDP.
#define UPDATE_RATE_HZ      30

// Coefficient du filtre passe-bas exponentiel (0.0 à 1.0).
// Plus la valeur est basse, plus le lissage est fort (mais plus de latence).
// 0.85 = très réactif (peu de latence). 0.5 = très lissé (plus de latence).
#define FILTER_ALPHA        0.85f

// Seuil de distance maximale (en mètres). 
// Les mesures au-delà sont considérées comme aberrantes et ignorées.
#define MAX_VALID_DISTANCE  30.0f

// Seuil de distance minimale (en mètres).
#define MIN_VALID_DISTANCE  0.1f

// Timeout en ms : si aucune mesure reçue d'un anchor pendant ce délai,
// il est considéré comme perdu.
// Le cycle UWB prend ~1.3s, donc 3s de timeout est raisonnable.
#define ANCHOR_TIMEOUT_MS   3000

// =========================
//   DEBUG
// =========================
// Mettre à 1 pour activer les logs série détaillés.
#define DEBUG_ENABLED       1

// Mettre à 1 pour envoyer aussi les distances brutes dans le paquet UDP.
#define SEND_RAW_DISTANCES  1
