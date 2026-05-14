// =============================================================================
// Network — Implémentation UDP WiFi + AP de secours OTA/Config
// =============================================================================

#include "network.h"
#include "config.h"
#include <ArduinoJson.h>
#include <Preferences.h>

// =============================================================================
// PAGE HTML — Config + bouton vers /update
// =============================================================================
static const char CONFIG_PAGE_TMPL[] PROGMEM = R"rawhtml(
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SudShow Locator — Configuration</title>
  <style>
    *    { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Segoe UI', sans-serif; background: #1a1a2e; color: #eee;
           min-height: 100vh; display: flex; flex-direction: column; align-items: center;
           padding: 2rem 1rem; }
    h1   { color: #f0a500; font-size: 1.4rem; margin-bottom: 0.3rem; }
    .sub { color: #888; font-size: 0.85rem; margin-bottom: 1.5rem; }
    .card { background: #16213e; border-radius: 10px; padding: 1.5rem;
            width: 100%; max-width: 440px; margin-bottom: 1rem; }
    h2   { color: #f0a500; font-size: 1rem; margin-bottom: 1rem; border-bottom: 1px solid #2a3a5e;
           padding-bottom: 0.5rem; }
    label  { display: block; margin-top: 1rem; font-size: 0.82rem; color: #aaa; }
    input  { width: 100%; padding: 0.55rem 0.75rem; margin-top: 0.3rem; border-radius: 5px;
             border: 1px solid #2a3a5e; background: #0f3460; color: #fff; font-size: 0.95rem; }
    input:focus { outline: none; border-color: #f0a500; }
    .btn-save { margin-top: 1.5rem; width: 100%; padding: 0.8rem; background: #f0a500;
                color: #000; font-weight: bold; font-size: 1rem; border: none;
                border-radius: 6px; cursor: pointer; transition: background .2s; }
    .btn-save:hover { background: #ffc040; }
    .btn-ota  { display: block; width: 100%; max-width: 440px; padding: 0.8rem;
                background: #0f3460; color: #f0a500; font-weight: bold; font-size: 1rem;
                border: 2px solid #f0a500; border-radius: 6px; cursor: pointer;
                text-align: center; text-decoration: none; transition: background .2s; }
    .btn-ota:hover { background: #1a4a80; }
    .info { font-size: 0.78rem; color: #666; margin-top: 0.4rem; }
  </style>
</head>
<body>
  <h1>📡 SudShow Locator</h1>
  <p class="sub">Mode configuration — AP: sudshow-locator &nbsp;|&nbsp; 192.168.4.1</p>

  <div class="card">
    <h2>🌐 Réseau WiFi &amp; UDP</h2>
    <form method="POST" action="/save">
      <label>WiFi SSID</label>
      <input name="ssid"     value="%%SSID%%"     placeholder="Nom du réseau">
      <label>Mot de passe WiFi</label>
      <input name="pass"     type="password" value="%%PASS%%"     placeholder="Mot de passe">
      <p class="info">Laisser vide pour conserver le mot de passe actuel.</p>
      <label>IP cible UDP (dashboard PC)</label>
      <input name="udp_ip"   value="%%UDP_IP%%"   placeholder="ex: 192.168.1.100">
      <p class="info">Utilisez 255.255.255.255 pour broadcast.</p>
      <label>Port UDP</label>
      <input name="udp_port" type="number" value="%%UDP_PORT%%" min="1" max="65535">
      <button class="btn-save" type="submit">💾 Sauvegarder et redémarrer</button>
    </form>
  </div>

  <a class="btn-ota" href="/update">🔧 Mettre à jour le firmware (OTA)</a>
</body>
</html>
)rawhtml";

static const char SAVE_OK_PAGE[] PROGMEM = R"rawhtml(
<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><title>Sauvegardé</title>
<style>
  body { font-family:'Segoe UI',sans-serif; background:#1a1a2e; color:#eee;
         display:flex; flex-direction:column; align-items:center;
         justify-content:center; min-height:100vh; text-align:center; }
  h1 { color:#4caf50; font-size:1.6rem; }
  p  { color:#aaa; margin-top:0.8rem; }
</style></head>
<body>
  <h1>✅ Configuration sauvegardée !</h1>
  <p>L'ESP32 redémarre dans 2 secondes…</p>
</body></html>
)rawhtml";

// =============================================================================
// CONSTRUCTEUR
// =============================================================================
Network::Network()
    : _server(80),
      _isListening(false),
      _apMode(false),
      _targetPort(UDP_TARGET_PORT),
      _packetCount(0),
      _lastReconnectAttempt(0),
      _lastDashboardHeartbeat(0),
      _lastHeartbeatSent(0) {
    strncpy(_targetIP, UDP_TARGET_IP, sizeof(_targetIP) - 1);
}

// =============================================================================
// setTarget — appelé depuis main.cpp après lecture NVS
// =============================================================================
void Network::setTarget(const char* ip, uint16_t port) {
    strncpy(_targetIP, ip, sizeof(_targetIP) - 1);
    _targetPort = port;
}

// =============================================================================
// connectWiFi
// =============================================================================
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
    if (_apMode) return WiFi.softAPIP().toString();
    return WiFi.localIP().toString();
}

bool Network::isAPMode() const {
    return _apMode;
}

// =============================================================================
// AP MODE — démarrage
// =============================================================================
String Network::_buildConfigPage(const String& ssid, const String& udpIP, uint16_t udpPort) {
    // Lire la config actuelle depuis NVS
    Preferences prefs;
    prefs.begin("netcfg", true);
    String curSSID  = prefs.getString("ssid",     ssid);
    String curUdpIP = prefs.getString("udp_ip",   udpIP);
    uint16_t curPort = prefs.getUShort("udp_port", udpPort);
    prefs.end();

    String page = String(CONFIG_PAGE_TMPL);
    page.replace("%%SSID%%",     curSSID);
    page.replace("%%PASS%%",     "");          // ne jamais pré-remplir le mot de passe
    page.replace("%%UDP_IP%%",   curUdpIP);
    page.replace("%%UDP_PORT%%", String(curPort));
    return page;
}

void Network::_registerRoutes() {
    // GET / → page de configuration
    _server.on("/", HTTP_GET, [this]() {
        String page = _buildConfigPage(WIFI_SSID, UDP_TARGET_IP, UDP_TARGET_PORT);
        _server.send(200, "text/html", page);
    });

    // POST /save → sauvegarde NVS + reboot
    _server.on("/save", HTTP_POST, [this]() {
        String newSSID    = _server.arg("ssid");
        String newPass    = _server.arg("pass");
        String newUdpIP   = _server.arg("udp_ip");
        String newUdpPort = _server.arg("udp_port");

        Preferences prefs;
        prefs.begin("netcfg", false);
        if (newSSID.length() > 0)    prefs.putString("ssid",     newSSID);
        if (newPass.length() > 0)    prefs.putString("pass",     newPass);
        if (newUdpIP.length() > 0)   prefs.putString("udp_ip",   newUdpIP);
        if (newUdpPort.length() > 0) prefs.putUShort("udp_port", (uint16_t)newUdpPort.toInt());
        prefs.end();

        Serial.printf("[NET] Config sauvegardée: ssid=%s udp=%s:%s\n",
                      newSSID.c_str(), newUdpIP.c_str(), newUdpPort.c_str());

        _server.send(200, "text/html", String(SAVE_OK_PAGE));
        delay(2000);
        ESP.restart();
    });

    // Toute autre route → rediriger vers /
    _server.onNotFound([this]() {
        _server.sendHeader("Location", "/", true);
        _server.send(302, "text/plain", "");
    });
}

void Network::startAPMode(const char* apSSID) {
    _apMode = true;

    WiFi.mode(WIFI_AP);
    WiFi.softAP(apSSID);  // Ouvert (sans mot de passe)
    delay(100);

    Serial.printf("[NET] ★ Mode AP: '%s' — IP: %s\n", apSSID,
                  WiFi.softAPIP().toString().c_str());
    Serial.println("[NET]   Ouvrir http://192.168.4.1/ pour configurer.");

    _registerRoutes();
    ElegantOTA.begin(&_server);
    _server.begin();

    Serial.println("[NET] Serveur web démarré.");
}

void Network::handleAP() {
    _server.handleClient();
    ElegantOTA.loop();
}

// =============================================================================
// ENVOI UDP (mode STA seulement)
// =============================================================================
void Network::sendPosition(float x, float y, float quality,
                            float d1, float d2, float d3,
                            bool sendDistances,
                            float batV) {
    if (!isConnected()) return;

    JsonDocument doc;
    doc["x"] = round(x * 1000.0f) / 1000.0f;
    doc["y"] = round(y * 1000.0f) / 1000.0f;
    doc["t"] = millis();
    doc["q"] = round(quality * 100.0f) / 100.0f;
    doc["n"] = _packetCount++;
    if (batV >= 0.0f) {
        doc["bat"] = round(batV * 100.0f) / 100.0f;
    }

    if (sendDistances) {
        JsonArray dArr = doc["d"].to<JsonArray>();
        dArr.add(round(d1 * 1000.0f) / 1000.0f);
        dArr.add(round(d2 * 1000.0f) / 1000.0f);
        dArr.add(round(d3 * 1000.0f) / 1000.0f);
    }

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
    if (isConnected() || _apMode) return;

    uint32_t now = millis();
    if (now - _lastReconnectAttempt < 5000) return;
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

            _lastDashboardHeartbeat = millis();

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

void Network::sendHeartbeat(float batV) {
    if (!isConnected()) return;

    uint32_t now = millis();
    if (now - _lastHeartbeatSent < 2000) return;
    _lastHeartbeatSent = now;

    char hb[64];
    if (batV >= 0.0f) {
        snprintf(hb, sizeof(hb), "{\"heartbeat\":1,\"bat\":%.2f}", batV);
    } else {
        snprintf(hb, sizeof(hb), "{\"heartbeat\":1}");
    }
    _udp.beginPacket(_targetIP, _targetPort);
    _udp.write((uint8_t*)hb, strlen(hb));
    _udp.endPacket();
}
