// =============================================================================
// Network — Implémentation UDP WiFi
// =============================================================================

#include "network.h"
#include "config.h"
#include <ArduinoJson.h>

Network::Network()
    : _targetIP(UDP_TARGET_IP),
      _targetPort(UDP_TARGET_PORT),
      _packetCount(0),
      _lastReconnectAttempt(0) {
}

bool Network::connectWiFi(const char* ssid, const char* password, uint32_t timeoutMs) {
    Serial.printf("[NET] Connexion WiFi '%s'...\n", ssid);

    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid, password);

    uint32_t start = millis();
    while (WiFi.status() != WL_CONNECTED) {
        if (millis() - start > timeoutMs) {
            Serial.println("[NET] ✗ Timeout connexion WiFi");
            return false;
        }
        delay(250);
        Serial.print(".");
    }

    Serial.println();
    Serial.printf("[NET] ✓ WiFi connecté ! IP: %s\n", WiFi.localIP().toString().c_str());
    Serial.printf("[NET]   RSSI: %d dBm\n", WiFi.RSSI());
    Serial.printf("[NET]   UDP target: %s:%u\n", _targetIP, _targetPort);

    return true;
}

bool Network::isConnected() const {
    return WiFi.status() == WL_CONNECTED;
}

String Network::getLocalIP() const {
    return WiFi.localIP().toString();
}

void Network::sendPosition(float x, float y, float quality,
                            float d1, float d2, float d3,
                            bool sendDistances) {
    if (!isConnected()) return;

    // Construire le JSON
    JsonDocument doc;
    doc["x"] = round(x * 1000.0f) / 1000.0f;  // 3 décimales (mm)
    doc["y"] = round(y * 1000.0f) / 1000.0f;
    doc["t"] = millis();
    doc["q"] = round(quality * 100.0f) / 100.0f;
    doc["n"] = _packetCount++;

    if (sendDistances) {
        JsonArray dArr = doc["d"].to<JsonArray>();
        dArr.add(round(d1 * 1000.0f) / 1000.0f);
        dArr.add(round(d2 * 1000.0f) / 1000.0f);
        dArr.add(round(d3 * 1000.0f) / 1000.0f);
    }

    // Sérialiser et envoyer
    char buffer[256];
    size_t len = serializeJson(doc, buffer, sizeof(buffer));

    _udp.beginPacket(_targetIP, _targetPort);
    _udp.write((uint8_t*)buffer, len);
    _udp.endPacket();

#if DEBUG_ENABLED
    if (_packetCount % 100 == 1) {
        Serial.printf("[NET] → UDP #%u: %s\n", _packetCount, buffer);
    }
#endif
}

void Network::maintainConnection() {
    if (isConnected()) return;

    uint32_t now = millis();
    if (now - _lastReconnectAttempt < 5000) return; // Pas plus d'une tentative toutes les 5s
    _lastReconnectAttempt = now;

    Serial.println("[NET] ⚠ WiFi déconnecté, tentative de reconnexion...");
    WiFi.reconnect();
}
