// =============================================================================
// SudShow Locator — Main (Dual-Core FreeRTOS)
// =============================================================================
// Architecture :
//   Core 1 — uwbTask  : Lecture UART BU-01 + trilatération (temps réel)
//   Core 0 — netTask  : WiFi, UDP, heartbeat, config, OLED
//
// Les deux tâches communiquent via SharedData protégé par un mutex.
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
Adafruit_SSD1306 oled(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);
#endif

// =============================================================================
// SHARED DATA — Communication inter-cœurs
// =============================================================================
struct SharedData {
    // Position calculée
    float x;
    float y;
    float quality;

    // Distances brutes (après offset)
    float distances[3];

    // État des anchors
    bool anchorsValid[3];
    bool allValid;
    uint32_t anchorAge[3];   // Âge de chaque mesure en ms

    // Statistiques
    uint32_t positionCount;
    uint32_t invalidCount;

    // Flag : nouvelle position disponible (consommé par netTask)
    bool newDataAvailable;

    // Calibration (écrit par netTask, lu par uwbTask)
    float offsets[3];
    float alpha;
    bool  calibrationUpdated;
};

static SharedData    sharedData;
static SemaphoreHandle_t dataMutex;

// =============================================================================
// INSTANCES — Chaque instance est utilisée par UN SEUL cœur
// =============================================================================
// Core 1 uniquement
static UWBReader      uwb;
static Trilateration  trilat;

// Core 0 uniquement
static Network        net;
static Preferences    prefs;

// =============================================================================
// CALIBRATION CALLBACK — Appelé depuis Core 0 (netTask)
// =============================================================================
static void onConfigReceived(float o0, float o1, float o2, float a) {
    // Sauvegarder en NVS
    prefs.putFloat("off0", o0);
    prefs.putFloat("off1", o1);
    prefs.putFloat("off2", o2);
    prefs.putFloat("alpha", a);

    // Passer les nouveaux paramètres au Core 1 via SharedData
    if (xSemaphoreTake(dataMutex, pdMS_TO_TICKS(10))) {
        sharedData.offsets[0] = o0;
        sharedData.offsets[1] = o1;
        sharedData.offsets[2] = o2;
        sharedData.alpha = a;
        sharedData.calibrationUpdated = true;
        xSemaphoreGive(dataMutex);
    }

    Serial.printf("[CONFIG] Nouveaux params reçus: A0=%.2f A1=%.2f A2=%.2f Alpha=%.2f\n", o0, o1, o2, a);
}

// =============================================================================
// CORE 1 — UWB TASK (Lecture UART + Trilatération)
// =============================================================================
// Priorité haute, boucle serrée — ne rate jamais de données UART.
// =============================================================================
static void uwbTask(void* param) {
    Serial.println("[CORE1] uwbTask démarrée");

    float currentAlpha = FILTER_ALPHA;

    for (;;) {
        // --- Lire les données UART ---
        uwb.update();

        // --- Vérifier si une nouvelle calibration est arrivée ---
        if (xSemaphoreTake(dataMutex, pdMS_TO_TICKS(1))) {
            if (sharedData.calibrationUpdated) {
                uwb.setOffsets(sharedData.offsets[0], sharedData.offsets[1], sharedData.offsets[2]);
                currentAlpha = sharedData.alpha;
                sharedData.calibrationUpdated = false;
            }
            xSemaphoreGive(dataMutex);
        }

        // --- Récupérer l'état des anchors ---
        bool anchorsValid[3];
        bool allValid = true;
        for (int i = 0; i < MAX_ANCHORS; i++) {
            anchorsValid[i] = uwb.isValid(i);
            if (!anchorsValid[i]) allValid = false;
        }

        // Toujours mettre à jour l'état des anchors (même si pas all valid)
        if (xSemaphoreTake(dataMutex, pdMS_TO_TICKS(5))) {
            for (int i = 0; i < MAX_ANCHORS; i++) {
                sharedData.anchorsValid[i] = anchorsValid[i];
                sharedData.anchorAge[i] = uwb.getAge(i);
            }
            sharedData.allValid = allValid;

            if (!allValid) {
                sharedData.invalidCount++;
                xSemaphoreGive(dataMutex);
                // Petite pause pour ne pas saturer le CPU quand il n'y a pas de données
                vTaskDelay(pdMS_TO_TICKS(1));
                continue;
            }

            // --- Distances ---
            float d0 = uwb.getDistance(0);
            float d1 = uwb.getDistance(1);
            float d2 = uwb.getDistance(2);

            // --- Trilatération ---
            Position2D rawPos = trilat.calculate(d0, d1, d2);

            if (!rawPos.valid) {
                sharedData.invalidCount++;
                rawPos.x = 0.0f;
                rawPos.y = 0.0f;
                rawPos.quality = 0.0f;
            }

            // --- Filtrage ---
            Position2D pos = trilat.filter(rawPos, currentAlpha);
            sharedData.positionCount++;

            // --- Écrire le résultat ---
            sharedData.x = pos.x;
            sharedData.y = pos.y;
            sharedData.quality = pos.quality;
            sharedData.distances[0] = d0;
            sharedData.distances[1] = d1;
            sharedData.distances[2] = d2;
            sharedData.newDataAvailable = true;

            xSemaphoreGive(dataMutex);
        }

        // Laisser respirer le scheduler (1ms)
        vTaskDelay(pdMS_TO_TICKS(1));
    }
}

// =============================================================================
// CORE 0 — NETWORK TASK (WiFi, UDP, Heartbeat, OLED)
// =============================================================================
// WiFi tourne nativement sur Core 0. Cette tâche gère toute la communication
// réseau et l'affichage.
// =============================================================================
static void netTask(void* param) {
    Serial.println("[CORE0] netTask démarrée");

    const uint32_t updateIntervalMs = 1000 / UPDATE_RATE_HZ;
    uint32_t lastUpdateTime = 0;
    uint32_t lastStatsTime  = 0;
    uint32_t displayCounter = 0;

    // Variables locales pour les données copiées depuis SharedData
    float posX = 0, posY = 0, posQ = 0;
    float dist[3] = {0, 0, 0};
    bool  anchValid[3] = {false, false, false};
    bool  allValid = false;
    uint32_t anchAge[3] = {9999, 9999, 9999};
    uint32_t posCount = 0, invCount = 0;
    bool  hasNewData = false;

    for (;;) {
        // --- Maintenir WiFi ---
        net.maintainConnection();

        // --- Lecture tension batterie (GPIO32) ---
#ifdef BOARD_TTGO
        uint32_t adcSum = 0;
        for (int s = 0; s < 8; s++) adcSum += analogRead(BAT_ADC_PIN);
        float batV = (adcSum / 8.0f / 4095.0f) * 3.3f * 2.0f;
#else
        float batV = -1.0f;
#endif

        // --- Heartbeat vers le dashboard ---
        net.sendHeartbeat(batV);

        // --- Écouter les configurations ---
        net.listenForConfig(5001, onConfigReceived);

        // --- Cadencer les mises à jour ---
        uint32_t now = millis();
        if (now - lastUpdateTime < updateIntervalMs) {
            vTaskDelay(pdMS_TO_TICKS(1));
            continue;
        }
        lastUpdateTime = now;

        // --- Lire les données partagées ---
        if (xSemaphoreTake(dataMutex, pdMS_TO_TICKS(10))) {
            posX = sharedData.x;
            posY = sharedData.y;
            posQ = sharedData.quality;
            dist[0] = sharedData.distances[0];
            dist[1] = sharedData.distances[1];
            dist[2] = sharedData.distances[2];
            for (int i = 0; i < 3; i++) {
                anchValid[i] = sharedData.anchorsValid[i];
                anchAge[i] = sharedData.anchorAge[i];
            }
            allValid = sharedData.allValid;
            posCount = sharedData.positionCount;
            invCount = sharedData.invalidCount;
            hasNewData = sharedData.newDataAvailable;
            sharedData.newDataAvailable = false;
            xSemaphoreGive(dataMutex);
        }

        // --- Envoi UDP si nouvelle position ---
        if (hasNewData && allValid) {
            net.sendPosition(posX, posY, posQ, dist[0], dist[1], dist[2], SEND_RAW_DISTANCES, batV);
        }

        // --- Affichage OLED (TTGO) — rafraîchi souvent pour le clignotement ---
#ifdef BOARD_TTGO
        {
            oled.clearDisplay();
            oled.setCursor(0, 0);
            oled.println("SudShow Locator");

            if (net.isConnected()) {
                oled.print("IP: "); oled.println(WiFi.localIP());
            } else {
                oled.println("WiFi: Offline");
            }

            // Indicateur dashboard : rond plein clignotant 4Hz si connecté
            const int cx = SCREEN_WIDTH - 5;
            const int cy = SCREEN_HEIGHT / 2;
            const int cr = 4;
            if (net.dashboardConnected()) {
                bool blink = (millis() / 125) % 2 == 0;
                if (blink) {
                    oled.fillCircle(cx, cy, cr, SSD1306_WHITE);
                }
            } else {
                oled.drawCircle(cx, cy, cr, SSD1306_WHITE);
            }

            // Batterie 18650 — réutilise batV déjà lu plus haut
            if (batV > 0.5f) {
                int batPct = (int)(((batV - BAT_EMPTY_V) / (BAT_FULL_V - BAT_EMPTY_V)) * 100.0f);
                if (batPct > 100) batPct = 100;
                if (batPct < 0)   batPct = 0;
                int bx = SCREEN_WIDTH - 26;
                int by = 0;
                oled.drawRect(bx, by, 20, 9, SSD1306_WHITE);
                oled.fillRect(bx + 20, by + 2, 3, 5, SSD1306_WHITE);
                int fillW = (int)(18.0f * batPct / 100.0f);
                if (fillW > 0) {
                    oled.fillRect(bx + 1, by + 1, fillW, 7, SSD1306_WHITE);
                }
            }

            if (allValid) {
                oled.print("Pos: "); oled.print(posX, 2); oled.print(", "); oled.println(posY, 2);
                oled.printf("A0:%.1f A1:%.1f A2:%.1f\n", dist[0], dist[1], dist[2]);
                oled.print("Q:"); oled.print(posQ * 100, 0); oled.print("%");
            } else {
                oled.println("Waiting anchors:");
                oled.print("A0:"); oled.print(anchValid[0] ? "OK " : "-- ");
                oled.print("A1:"); oled.print(anchValid[1] ? "OK " : "-- ");
                oled.print("A2:"); oled.println(anchValid[2] ? "OK" : "--");
            }

            // Rectangles d'activité par anchor (dernière ligne)
            // Chaque rect flash plein pendant 200ms après réception d'une mesure
            int rectW = SCREEN_WIDTH / 3 - 4;
            int rectH = 6;
            int rectY = SCREEN_HEIGHT - rectH - 1;
            for (int i = 0; i < 3; i++) {
                int rectX = i * (SCREEN_WIDTH / 3) + 2;
                if (anchAge[i] < 200) {
                    // Mesure fraîche → rectangle plein
                    oled.fillRect(rectX, rectY, rectW, rectH, SSD1306_WHITE);
                } else {
                    // Pas de mesure récente → rectangle vide
                    oled.drawRect(rectX, rectY, rectW, rectH, SSD1306_WHITE);
                }
                // Label centré sous le rect
                oled.setCursor(rectX + rectW/2 - 6, rectY - 9);
                oled.printf("A%d", i);
            }

            oled.display();
        }
#endif

        // --- Stats périodiques (toutes les 5 secondes) ---
        if (now - lastStatsTime >= 5000) {
            lastStatsTime = now;
            Serial.println("────────────────────────────────────────────");
            if (allValid) {
                Serial.printf("[STATS] Position: (%.3f, %.3f) m  Qualité: %.0f%%\n",
                              posX, posY, posQ * 100.0f);
                Serial.printf("[STATS] Distances: A0=%.3fm  A1=%.3fm  A2=%.3fm\n",
                              dist[0], dist[1], dist[2]);
            } else {
                Serial.printf("[STATS] En attente: A0=%s A1=%s A2=%s\n",
                              anchValid[0] ? "✓" : "✗",
                              anchValid[1] ? "✓" : "✗",
                              anchValid[2] ? "✓" : "✗");
            }
            Serial.printf("[STATS] Paquets: %u envoyés, %u invalides\n",
                          posCount, invCount);
            Serial.printf("[STATS] WiFi: %s (RSSI: %d dBm)\n",
                          net.isConnected() ? "✓" : "✗",
                          WiFi.RSSI());
            Serial.printf("[STATS] Dashboard: %s\n",
                          net.dashboardConnected() ? "✓ Connecté" : "✗ Pas de lien");
            Serial.printf("[STATS] Anchors age: A0=%ums A1=%ums A2=%ums\n",
                          uwb.getAge(0), uwb.getAge(1), uwb.getAge(2));
            Serial.printf("[STATS] FreeRAM: %u bytes\n", ESP.getFreeHeap());
#ifdef BOARD_TTGO
            Serial.printf("[STATS] Batterie GPIO32: %.2fV\n", batV);
#endif
        }

        // Petit yield pour ne pas starver le système
        vTaskDelay(pdMS_TO_TICKS(1));
    }
}

// =============================================================================
// SETUP — Initialisation hardware + lancement des tâches
// =============================================================================
void setup() {
    Serial.begin(115200);
    delay(1000);

    Serial.println();
    Serial.println("╔══════════════════════════════════════════╗");
    Serial.println("║   SudShow Locator — ESP32 Dual-Core     ║");
    Serial.println("╚══════════════════════════════════════════╝");
    Serial.println();

    // --- Créer le mutex ---
    dataMutex = xSemaphoreCreateMutex();

    // --- Initialiser SharedData ---
    memset(&sharedData, 0, sizeof(SharedData));
    sharedData.alpha = FILTER_ALPHA;
    sharedData.offsets[0] = ANCHOR1_OFFSET;
    sharedData.offsets[1] = ANCHOR2_OFFSET;
    sharedData.offsets[2] = ANCHOR3_OFFSET;

    Serial.printf("[MAIN] Fréquence cible: %d Hz\n", UPDATE_RATE_HZ);

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
    }

    // --- Initialiser la liaison UWB ---
    uwb.begin(Serial2, UWB_SERIAL_RX, UWB_SERIAL_TX, UWB_BAUD_RATE);

    // --- Charger la calibration depuis NVS ---
    prefs.begin("uwb", false);
    float o0 = prefs.getFloat("off0", ANCHOR1_OFFSET);
    float o1 = prefs.getFloat("off1", ANCHOR2_OFFSET);
    float o2 = prefs.getFloat("off2", ANCHOR3_OFFSET);
    float alpha = prefs.getFloat("alpha", FILTER_ALPHA);
    uwb.setOffsets(o0, o1, o2);
    sharedData.offsets[0] = o0;
    sharedData.offsets[1] = o1;
    sharedData.offsets[2] = o2;
    sharedData.alpha = alpha;
    Serial.printf("[MAIN] Calibration: A0=%.2f A1=%.2f A2=%.2f Alpha=%.2f\n", o0, o1, o2, alpha);

    // --- Init module UWB ---
    bool atReady = uwb.initModule();
    if (!atReady) {
        Serial.println("[MAIN] ⚠ Module non détecté en mode AT — écoute passive.");
    }

    // --- OLED + Batterie (TTGO) ---
#ifdef BOARD_TTGO
    Wire.begin(OLED_SDA, OLED_SCL);
    analogSetAttenuation(ADC_11db);
    pinMode(BAT_ADC_PIN, INPUT);
    if (!oled.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
        Serial.println("[MAIN] ⚠ Échec initialisation OLED");
    } else {
        oled.clearDisplay();
        oled.setRotation(2);  // 180°
        oled.setTextSize(1);
        oled.setTextColor(SSD1306_WHITE);
        oled.setCursor(0, 0);
        oled.println("SudShow Locator");
        oled.println("Dual-Core Ready!");
        oled.display();
    }
#endif

    // --- Lancer les tâches FreeRTOS ---
    Serial.println();
    Serial.println("[MAIN] Lancement des tâches FreeRTOS...");

    // uwbTask sur Core 1, priorité 2, stack 4KB
    xTaskCreatePinnedToCore(
        uwbTask,    // Fonction
        "uwbTask",  // Nom
        4096,       // Stack (bytes)
        NULL,       // Paramètre
        2,          // Priorité (haute)
        NULL,       // Handle (pas besoin)
        1           // Core 1
    );

    // netTask sur Core 0, priorité 1, stack 8KB (WiFi + JSON + OLED)
    xTaskCreatePinnedToCore(
        netTask,    // Fonction
        "netTask",  // Nom
        8192,       // Stack (bytes) — plus grand pour WiFi/JSON/OLED
        NULL,       // Paramètre
        1,          // Priorité (normale)
        NULL,       // Handle
        0           // Core 0
    );

    Serial.println("[MAIN] ✓ Tâches lancées — uwbTask(Core1) + netTask(Core0)");
    Serial.println("────────────────────────────────────────────");
}

// =============================================================================
// LOOP — Vide (tout est dans les tâches FreeRTOS)
// =============================================================================
void loop() {
    // Le loop Arduino tourne sur Core 1 avec priorité 1.
    // On le laisse dormir car uwbTask gère tout sur Core 1.
    vTaskDelay(pdMS_TO_TICKS(1000));
}
