// =============================================================================
// UWB Reader — Implémentation
// =============================================================================

#include "uwb_reader.h"
#include "config.h"

UWBReader::UWBReader()
    : _serial(nullptr), _bufferPos(0), _timeoutMs(ANCHOR_TIMEOUT_MS) {
    for (int i = 0; i < MAX_ANCHORS; i++) {
        _anchors[i].distance       = 0.0f;
        _anchors[i].lastUpdateTime = 0;
        _anchors[i].valid          = false;
        _anchors[i].updateCount    = 0;
    }
}

void UWBReader::begin(HardwareSerial& serial, int rxPin, int txPin, uint32_t baudRate) {
    _serial = &serial;
    _serial->begin(baudRate, SERIAL_8N1, rxPin, txPin);
    _bufferPos = 0;

#if DEBUG_ENABLED
    Serial.println("[UWB] UART initialisé");
    Serial.printf("[UWB]   RX=%d, TX=%d, Baud=%u\n", rxPin, txPin, baudRate);
#endif
}

bool UWBReader::initModule() {
    if (!_serial) return false;

#if DEBUG_ENABLED
    Serial.println("[UWB] Mode écoute passive haute vitesse activé");
#endif

    // Plus de commandes AT: on écoute juste le flux C++ personnalisé à haute vitesse
    return true;
}

void UWBReader::sendCommand(const char* cmd) {
    if (!_serial) return;
    _serial->print(cmd);
    _serial->print("\r\n");

#if DEBUG_ENABLED
    Serial.printf("[UWB] → %s\n", cmd);
#endif
}

void UWBReader::update() {
    if (!_serial) return;

    // Lire les caractères disponibles
    while (_serial->available()) {
        char c = _serial->read();

        if (c == '\n' || c == '\r') {
            if (_bufferPos > 0) {
                _buffer[_bufferPos] = '\0';
                parseLine(_buffer);
                _bufferPos = 0;
            }
        } else if (_bufferPos < sizeof(_buffer) - 1) {
            _buffer[_bufferPos++] = c;
        } else {
            // Buffer overflow — reset
            _bufferPos = 0;
        }
    }

    // Vérifier les timeouts
    uint32_t now = millis();
    for (int i = 0; i < MAX_ANCHORS; i++) {
        if (_anchors[i].valid && (now - _anchors[i].lastUpdateTime > _timeoutMs)) {
            _anchors[i].valid = false;
#if DEBUG_ENABLED
            Serial.printf("[UWB] ⚠ Anchor %d timeout\n", i);
#endif
        }
    }
}

void UWBReader::parseLine(const char* line) {
#if DEBUG_ENABLED
    Serial.printf("[UWB] ← %s\n", line);
#endif

    // Auto-détection du format
    if (strncmp(line, "an", 2) == 0 || strncmp(line, "AN", 2) == 0) {
        // Format Ai-Thinker : "an0:1.234" ou "AN0:1.234"
        parseAiThinkerFormat(line);
    } else if (strncmp(line, "DIST", 4) == 0 || strncmp(line, "dist", 4) == 0) {
        // Format DIST : "DIST:0=1.234,1=2.345,2=3.456"
        parseDistFormat(line);
    } else if (line[0] == '$') {
        // Format compact : "$1.234,2.345,3.456"
        parseCompactFormat(line);
    } else if (strncmp(line, "mc", 2) == 0) {
        // Format DWM1001 : "mc 0 x y z qf an0 d0 qf0 an1 d1 qf1 ..."
        // Extraire les distances
        // Ce format est courant dans les firmwares Decawave/Qorvo
        parseDistFormat(line);
    }
    // Sinon, on ignore la ligne (peut être "OK", version info, etc.)
}

void UWBReader::parseAiThinkerFormat(const char* line) {
    // Format: "an0:1.234" ou "an1:2.345"
    // Le chiffre après "an" est l'index de l'anchor (0, 1, 2)
    int offset = 2;
    if (line[offset] >= '0' && line[offset] <= '9') {
        uint8_t index = line[offset] - '0';
        // Chercher le ':'
        const char* colon = strchr(line + offset, ':');
        if (colon) {
            float distance = atof(colon + 1);
            updateAnchor(index, distance);
        }
    }
}

void UWBReader::parseDistFormat(const char* line) {
    // Format: "DIST:0=1.234,1=2.345,2=3.456"
    const char* p = strchr(line, ':');
    if (!p) p = line;
    else p++;

    while (*p) {
        // Chercher "N=" pattern
        if (*p >= '0' && *p <= '9') {
            uint8_t index = *p - '0';
            if (*(p + 1) == '=') {
                float distance = atof(p + 2);
                updateAnchor(index, distance);
            }
        }
        // Avancer au prochain segment
        const char* next = strchr(p, ',');
        if (next) p = next + 1;
        else break;
    }
}

void UWBReader::parseCompactFormat(const char* line) {
    // Format: "$1.234,2.345,3.456"
    const char* p = line + 1; // Skip '$'
    for (uint8_t i = 0; i < MAX_ANCHORS && *p; i++) {
        float distance = atof(p);
        updateAnchor(i, distance);
        const char* next = strchr(p, ',');
        if (next) p = next + 1;
        else break;
    }
}

void UWBReader::updateAnchor(uint8_t index, float distance) {
    if (index >= MAX_ANCHORS) return;
    if (!isValidDistance(distance)) {
#if DEBUG_ENABLED
        Serial.printf("[UWB] ✗ Anchor %d distance invalide: %.3f m\n", index, distance);
#endif
        return;
    }

    _anchors[index].distance       = distance;
    _anchors[index].lastUpdateTime = millis();
    _anchors[index].valid          = true;
    _anchors[index].updateCount++;

#if DEBUG_ENABLED
    if (_anchors[index].updateCount % 50 == 1) {
        Serial.printf("[UWB] ✓ Anchor %d: %.3f m (count=%u)\n",
                      index, distance, _anchors[index].updateCount);
    }
#endif
}

bool UWBReader::isValidDistance(float d) const {
    return (d >= MIN_VALID_DISTANCE && d <= MAX_VALID_DISTANCE && !isnan(d) && !isinf(d));
}

float UWBReader::getDistance(uint8_t index) const {
    if (index >= MAX_ANCHORS) return 0.0f;
    return _anchors[index].distance;
}

bool UWBReader::isValid(uint8_t index) const {
    if (index >= MAX_ANCHORS) return false;
    return _anchors[index].valid;
}

bool UWBReader::allAnchorsValid() const {
    for (int i = 0; i < MAX_ANCHORS; i++) {
        if (!_anchors[i].valid) return false;
    }
    return true;
}

uint32_t UWBReader::getAge(uint8_t index) const {
    if (index >= MAX_ANCHORS) return UINT32_MAX;
    return millis() - _anchors[index].lastUpdateTime;
}
