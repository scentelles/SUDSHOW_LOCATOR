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
#include <Preferences.h>

#ifdef BOARD_TTGO
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);
#endif

// --- Instances globales ---
UWBReader      uwb;
Trilateration  trilat;
Network        net;
Preferences    prefs;

float current_alpha = FILTER_ALPHA;

void onConfigReceived(float o0, float o1, float o2, float a) {
    uwb.setOffsets(o0, o1, o2);
    current_alpha = a;
    prefs.putFloat("off0", o0);
    prefs.putFloat("off1", o1);
    prefs.putFloat("off2", o2);
    prefs.putFloat("alpha", a);
    Serial.printf("[CONFIG] Nouveaux params reçus: A0=%.2f A1=%.2f A2=%.2f Alpha=%.2f\n", o0, o1, o2, a);
}

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

    // --- Charger les offsets et params de calibration ---
    prefs.begin("uwb", false);
    float o0 = prefs.getFloat("off0", ANCHOR1_OFFSET);
    float o1 = prefs.getFloat("off1", ANCHOR2_OFFSET);
    float o2 = prefs.getFloat("off2", ANCHOR3_OFFSET);
    current_alpha = prefs.getFloat("alpha", FILTER_ALPHA);
    uwb.setOffsets(o0, o1, o2);
    Serial.printf("[MAIN] Calibration chargée : A0=%.2f A1=%.2f A2=%.2f Alpha=%.2f\n", o0, o1, o2, current_alpha);

    // Tenter l'initialisation AT firmware
    bool atReady = uwb.initModule();
    if (!atReady) {
        Serial.println("[MAIN] ⚠ Module non détecté en mode AT.");
        Serial.println("[MAIN]   Passage en mode écoute passive (lecture UART).");
    }

    Serial.println();
    Serial.println("[MAIN] ✓ Système prêt — en attente des données UWB...");
    Serial.println("────────────────────────────────────────────");

#ifdef BOARD_TTGO
    Wire.begin(OLED_SDA, OLED_SCL);
    if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
        Serial.println("[MAIN] ⚠ Échec initialisation OLED");
    } else {
        display.clearDisplay();
        display.setTextSize(1);
        display.setTextColor(SSD1306_WHITE);
        display.setCursor(0,0);
        display.println("SudShow Locator");
        display.println("System Ready!");
        display.display();
    }
#endif
}

// =============================================================================
void loop() {
    loopCount++;

    // --- Toujours lire les données UWB ---
    uwb.update();

    // --- Maintenir la connexion WiFi ---
    net.maintainConnection();

    // --- Heartbeat vers le dashboard (même sans UWB) ---
    net.sendHeartbeat();

    // --- Écouter les nouvelles configurations de calibration ---
    net.listenForConfig(5001, onConfigReceived);

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
#ifdef BOARD_TTGO
            display.clearDisplay();
            display.setCursor(0,0);
            display.println("SudShow Locator");
            if (net.isConnected()) {
                display.print("IP: "); display.println(WiFi.localIP());
            } else {
                display.println("WiFi: Offline");
            }
            display.print("Dash: ");
            display.println(net.dashboardConnected() ? "OK" : "--");
            display.println("Waiting anchors:");
            display.print("A0:"); display.print(uwb.isValid(0) ? "OK " : "-- ");
            display.print("A1:"); display.print(uwb.isValid(1) ? "OK " : "-- ");
            display.print("A2:"); display.println(uwb.isValid(2) ? "OK" : "--");
            display.display();
#endif
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
        // On n'abandonne PLUS l'envoi UDP ! On force une position factice
        // pour laisser le PC calculer la trilatération 3D.
        rawPos.x = 0.0f;
        rawPos.y = 0.0f;
        rawPos.quality = 0.0f;
    }

    // --- Filtrage ---
    Position2D pos = trilat.filter(rawPos, current_alpha);
    positionCount++;

    // --- Envoi UDP ---
    net.sendPosition(pos.x, pos.y, pos.quality, d0, d1, d2, SEND_RAW_DISTANCES);

#ifdef BOARD_TTGO
    static uint32_t displayCounter = 0;
    if (displayCounter++ % 15 == 0) { // Update approx twice per second
        display.clearDisplay();
        display.setCursor(0,0);
        display.println("SudShow Locator");
        if (net.isConnected()) {
            display.print("IP: "); display.println(WiFi.localIP());
        } else {
            display.println("WiFi: Offline");
        }
        display.print("Dash: ");
        display.println(net.dashboardConnected() ? "OK" : "--");
        display.print("Pos: "); display.print(pos.x, 2); display.print(", "); display.println(pos.y, 2);
        display.printf("A0:%.1f A1:%.1f A2:%.1f\n", d0, d1, d2);
        display.print("Q:"); display.print(pos.quality * 100, 0); display.print("%");
        display.display();
    }
#endif

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
