// =============================================================================
// Network — Implémentation UDP WiFi
// =============================================================================

#include "network.h"
#include "config.h"
#include <ArduinoJson.h>

Network::Network()
    : _isListening(false),
      _targetIP(UDP_TARGET_IP),
      _targetPort(UDP_TARGET_PORT),
      _packetCount(0),
      _lastReconnectAttempt(0),
      _lastDashboardHeartbeat(0),
      _lastHeartbeatSent(0) {
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

void Network::listenForConfig(uint16_t localPort, void (*onConfigReceived)(float, float, float, float)) {
    if (!isConnected()) return;

    if (!_isListening) {
        if (_udpRx.begin(localPort)) {
            Serial.printf("[NET] Écoute UDP sur le port %u\n", localPort);
            _isListening = true;
        } else {
            return;
        }
    }

    int packetSize = _udpRx.parsePacket();
    if (packetSize > 0) {
        char buffer[256];
        int len = _udpRx.read(buffer, sizeof(buffer) - 1);
        if (len > 0) {
            buffer[len] = '\0';
            
            // Tout paquet reçu du dashboard = heartbeat
            _lastDashboardHeartbeat = millis();
            
            // Format attendu: {"off0":0.8, "off1":0.8, "off2":0.8, "alpha":0.5}
            // ou bien: {"ping":1} pour le heartbeat simple
            JsonDocument doc;
            DeserializationError err = deserializeJson(doc, buffer);
            if (!err) {
                if (doc.containsKey("off0") && doc.containsKey("off1") && doc.containsKey("off2")) {
                    float o0 = doc["off0"].as<float>();
                    float o1 = doc["off1"].as<float>();
                    float o2 = doc["off2"].as<float>();
                    float a  = doc.containsKey("alpha") ? doc["alpha"].as<float>() : 0.5f;
                    
                    if (onConfigReceived) {
                        onConfigReceived(o0, o1, o2, a);
                    }
                }
                // ping packets are silently accepted (heartbeat already updated)
            } else {
                Serial.println("[NET] ✗ Erreur JSON entrant");
            }
        }
    }
}

bool Network::dashboardConnected() const {
    if (_lastDashboardHeartbeat == 0) return false;
    return (millis() - _lastDashboardHeartbeat) < 5000;
}

void Network::sendHeartbeat() {
    if (!isConnected()) return;

    uint32_t now = millis();
    if (now - _lastHeartbeatSent < 2000) return;  // Toutes les 2 secondes
    _lastHeartbeatSent = now;

    // Envoyer un petit paquet heartbeat au dashboard
    const char* hb = "{\"heartbeat\":1}";
    _udp.beginPacket(_targetIP, _targetPort);
    _udp.write((uint8_t*)hb, strlen(hb));
    _udp.endPacket();
}
