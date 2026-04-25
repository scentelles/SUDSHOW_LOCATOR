#pragma once
// =============================================================================
// UWB Reader — Lecture des distances depuis le Tag BU-01
// =============================================================================
// Le module BU-01 en mode Tag envoie les distances via UART.
// Formats supportés (auto-détection) :
//   Format 1 : "an0:1.234\r\n"  (Ai-Thinker AT firmware)
//   Format 2 : "DIST:0=1.234,1=2.345,2=3.456\r\n"
//   Format 3 : "$1.234,2.345,3.456\r\n"  (custom compact)
// =============================================================================

#include <Arduino.h>

// Nombre maximum d'anchors supportés
#define MAX_ANCHORS 3

struct AnchorData {
    float    distance;         // Distance en mètres
    uint32_t lastUpdateTime;   // Timestamp de la dernière mesure (millis)
    bool     valid;            // Mesure valide et récente ?
    uint32_t updateCount;      // Compteur de mises à jour
};

class UWBReader {
public:
    UWBReader();

    /// Initialise la communication série avec le Tag BU-01
    void begin(HardwareSerial& serial, int rxPin, int txPin, uint32_t baudRate);

    /// À appeler dans loop() — lit et parse les données série
    void update();

    /// Renvoie la distance du anchor `index` (0, 1, 2)
    float getDistance(uint8_t index) const;

    /// Vérifie si la mesure du anchor `index` est valide et récente
    bool isValid(uint8_t index) const;

    /// Vérifie si les 3 anchors ont des mesures valides
    bool allAnchorsValid() const;

    /// Renvoie l'âge de la dernière mesure en ms
    uint32_t getAge(uint8_t index) const;

    /// Envoie une commande AT au module
    void sendCommand(const char* cmd);

    /// Tente d'initialiser le module (AT test + config tag + start ranging)
    bool initModule();

private:
    HardwareSerial* _serial;
    AnchorData      _anchors[MAX_ANCHORS];
    char            _buffer[256];
    uint8_t         _bufferPos;
    uint32_t        _timeoutMs;

    void parseLine(const char* line);
    void parseAiThinkerFormat(const char* line);
    void parseDistFormat(const char* line);
    void parseCompactFormat(const char* line);
    void updateAnchor(uint8_t index, float distance);
    bool isValidDistance(float d) const;
};
