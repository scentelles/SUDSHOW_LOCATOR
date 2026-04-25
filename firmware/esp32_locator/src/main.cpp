// =============================================================================
// SudShow Locator — Main
// =============================================================================
// ESP32 firmware : lit les distances UWB du Tag BU-01, calcule la position
// par trilatération, et envoie les coordonnées via UDP WiFi.
// =============================================================================

#include <Arduino.h>
#include "config.h"
#include "uwb_reader.h"
#include "trilateration.h"
#include "network.h"

// --- Instances globales ---
UWBReader      uwb;
Trilateration  trilat;
Network        net;

// --- Timing ---
uint32_t lastUpdateTime  = 0;
uint32_t updateIntervalMs;

// --- Stats ---
uint32_t positionCount    = 0;
uint32_t invalidCount     = 0;
uint32_t loopCount        = 0;
uint32_t lastStatsTime    = 0;

// =============================================================================
void setup() {
    Serial.begin(115200);
    delay(1000);

    Serial.println();
    Serial.println("╔══════════════════════════════════════════╗");
    Serial.println("║   SudShow Locator — ESP32 UWB Tracker   ║");
    Serial.println("╚══════════════════════════════════════════╝");
    Serial.println();

    // Calculer l'intervalle de mise à jour
    updateIntervalMs = 1000 / UPDATE_RATE_HZ;
    Serial.printf("[MAIN] Fréquence: %d Hz (intervalle: %u ms)\n",
                  UPDATE_RATE_HZ, updateIntervalMs);

    // --- Configurer la trilatération ---
    trilat.setAnchorPosition(0, ANCHOR1_X, ANCHOR1_Y);
    trilat.setAnchorPosition(1, ANCHOR2_X, ANCHOR2_Y);
    trilat.setAnchorPosition(2, ANCHOR3_X, ANCHOR3_Y);

    Serial.printf("[MAIN] Anchors:\n");
    Serial.printf("  A0: (%.2f, %.2f)\n", ANCHOR1_X, ANCHOR1_Y);
    Serial.printf("  A1: (%.2f, %.2f)\n", ANCHOR2_X, ANCHOR2_Y);
    Serial.printf("  A2: (%.2f, %.2f)\n", ANCHOR3_X, ANCHOR3_Y);

    // --- Initialiser le WiFi ---
    if (!net.connectWiFi(WIFI_SSID, WIFI_PASS)) {
        Serial.println("[MAIN] ⚠ WiFi non connecté — les données ne seront pas envoyées.");
        Serial.println("[MAIN]   Le positionnement continue en local.");
    }

    // --- Initialiser la liaison UWB ---
    uwb.begin(Serial2, UWB_SERIAL_RX, UWB_SERIAL_TX, UWB_BAUD_RATE);

    // Tenter l'initialisation AT firmware
    bool atReady = uwb.initModule();
    if (!atReady) {
        Serial.println("[MAIN] ⚠ Module non détecté en mode AT.");
        Serial.println("[MAIN]   Passage en mode écoute passive (lecture UART).");
    }

    Serial.println();
    Serial.println("[MAIN] ✓ Système prêt — en attente des données UWB...");
    Serial.println("────────────────────────────────────────────");
}

// =============================================================================
void loop() {
    loopCount++;

    // --- Toujours lire les données UWB ---
    uwb.update();

    // --- Maintenir la connexion WiFi ---
    net.maintainConnection();

    // --- Calcul et envoi à fréquence fixe ---
    uint32_t now = millis();
    if (now - lastUpdateTime < updateIntervalMs) {
        return;
    }
    lastUpdateTime = now;

    // --- Vérifier que les 3 anchors ont des données valides ---
    if (!uwb.allAnchorsValid()) {
        invalidCount++;
        // Afficher un statut périodique
        if (invalidCount % (UPDATE_RATE_HZ * 2) == 1) {
            Serial.printf("[MAIN] ⏳ En attente des anchors : A0=%s A1=%s A2=%s\n",
                          uwb.isValid(0) ? "✓" : "✗",
                          uwb.isValid(1) ? "✓" : "✗",
                          uwb.isValid(2) ? "✓" : "✗");
        }
        return;
    }

    // --- Récupérer les distances ---
    float d0 = uwb.getDistance(0);
    float d1 = uwb.getDistance(1);
    float d2 = uwb.getDistance(2);

    // --- Trilatération ---
    Position2D rawPos = trilat.calculate(d0, d1, d2);

    if (!rawPos.valid) {
        invalidCount++;
        return;
    }

    // --- Filtrage ---
    Position2D pos = trilat.filter(rawPos, FILTER_ALPHA);
    positionCount++;

    // --- Envoi UDP ---
    net.sendPosition(pos.x, pos.y, pos.quality, d0, d1, d2, SEND_RAW_DISTANCES);

    // --- Stats périodiques (toutes les 5 secondes) ---
    if (now - lastStatsTime >= 5000) {
        lastStatsTime = now;
        Serial.println("────────────────────────────────────────────");
        Serial.printf("[STATS] Position: (%.3f, %.3f) m  Qualité: %.0f%%\n",
                      pos.x, pos.y, pos.quality * 100.0f);
        Serial.printf("[STATS] Distances: A0=%.3fm  A1=%.3fm  A2=%.3fm\n",
                      d0, d1, d2);
        Serial.printf("[STATS] Paquets: %u envoyés, %u invalides\n",
                      positionCount, invalidCount);
        Serial.printf("[STATS] WiFi: %s (RSSI: %d dBm)\n",
                      net.isConnected() ? "✓" : "✗",
                      WiFi.RSSI());
        Serial.printf("[STATS] Anchors age: A0=%ums A1=%ums A2=%ums\n",
                      uwb.getAge(0), uwb.getAge(1), uwb.getAge(2));
    }
}
