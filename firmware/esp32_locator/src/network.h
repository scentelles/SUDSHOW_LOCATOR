#pragma once
// =============================================================================
// Network — Envoi UDP WiFi
// =============================================================================

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>

class Network {
public:
    Network();

    /// Se connecte au WiFi (bloquant, avec timeout)
    bool connectWiFi(const char* ssid, const char* password, uint32_t timeoutMs = 10000);

    /// Vérifie si le WiFi est connecté
    bool isConnected() const;

    /// Renvoie l'adresse IP locale
    String getLocalIP() const;

    /// Envoie un paquet UDP avec la position
    /// Format JSON : {"x":3.45, "y":2.10, "t":12345678, "q":0.95, "d":[1.2, 3.4, 2.1]}
    void sendPosition(float x, float y, float quality,
                      float d1, float d2, float d3,
                      bool sendDistances = true);

    /// Tente de reconnecter le WiFi si déconnecté
    void maintainConnection();

    /// Écoute les paquets UDP entrants (ex: calibration)
    void listenForConfig(uint16_t localPort, void (*onConfigReceived)(float, float, float, float));

    /// Envoie un heartbeat périodique au dashboard (toutes les 2s)
    void sendHeartbeat();

    /// Vérifie si le dashboard PC a envoyé un heartbeat récemment
    bool dashboardConnected() const;

private:
    WiFiUDP _udp;
    WiFiUDP _udpRx;
    bool    _isListening;
    const char* _targetIP;
    uint16_t    _targetPort;
    uint32_t    _packetCount;
    uint32_t    _lastReconnectAttempt;
    uint32_t    _lastDashboardHeartbeat;
    uint32_t    _lastHeartbeatSent;
};
