#pragma once
// =============================================================================
// Network — Envoi UDP WiFi + AP de secours OTA/Config
// =============================================================================

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <WebServer.h>
#include <ElegantOTA.h>

class Network {
public:
    Network();

    /// Se connecte au WiFi STA (bloquant, avec timeout)
    bool connectWiFi(const char* ssid, const char* password, uint32_t timeoutMs = 10000);

    /// Définit la cible UDP (IP + port) — doit être appelé avant toute émission
    void setTarget(const char* ip, uint16_t port);

    /// Vérifie si le WiFi STA est connecté
    bool isConnected() const;

    /// Renvoie l'adresse IP locale (STA ou AP)
    String getLocalIP() const;

    /// Envoie un paquet UDP avec la position
    /// Format JSON : {"x":3.45, "y":2.10, "t":12345678, "q":0.95, "d":[1.2, 3.4, 2.1]}
    void sendPosition(float x, float y, float quality,
                      float d1, float d2, float d3,
                      bool sendDistances = true,
                      float batV = -1.0f);

    /// Tente de reconnecter le WiFi si déconnecté (mode STA uniquement)
    void maintainConnection();

    /// Écoute les paquets UDP entrants (ex: calibration)
    void listenForConfig(uint16_t localPort, void (*onConfigReceived)(float, float, float, float));

    /// Envoie un heartbeat périodique au dashboard (toutes les 2s)
    void sendHeartbeat(float batV = -1.0f);

    /// Vérifie si le dashboard PC a envoyé un heartbeat récemment
    bool dashboardConnected() const;

    // =========================================================================
    // MODE AP DE SECOURS — OTA + Configuration réseau
    // =========================================================================

    /// Démarre le mode Access Point + serveur web de config + ElegantOTA
    /// apSSID : nom du réseau WiFi créé (ex: "sudshow-locator")
    void startAPMode(const char* apSSID);

    /// À appeler en boucle quand isAPMode() == true
    void handleAP();

    /// Retourne true si l'ESP32 est en mode AP de secours
    bool isAPMode() const;

private:
    WiFiUDP    _udp;
    WiFiUDP    _udpRx;
    WebServer  _server;

    bool       _isListening;
    bool       _apMode;

    char       _targetIP[64];
    uint16_t   _targetPort;
    uint32_t   _packetCount;
    uint32_t   _lastReconnectAttempt;
    uint32_t   _lastDashboardHeartbeat;
    uint32_t   _lastHeartbeatSent;

    // NVS keys pour la config réseau (lues/écrites dans main.cpp)
    void _registerRoutes();
    String _buildConfigPage(const String& ssid, const String& udpIP, uint16_t udpPort);
};
