#ifndef PINOUT_H
#define PINOUT_H

#include <Arduino.h>

// =========================================================================
// NodeMCU-BU01 (AIT-BU01-DB V1.1) to DW1000 Hardware Pinout
// =========================================================================

#define PIN_SPI_SS    PA4
#define PIN_SPI_SCK   PA5
#define PIN_SPI_MISO  PA6
#define PIN_SPI_MOSI  PA7

#define PIN_IRQ       PB0
#define PIN_RST       PB12

// Note : WAKEUP est sur PB13 (actif haut), EXTON sur PB14

inline void initHardwarePins() {
    // S'assurer que le Pin RST est correctement configuré
    pinMode(PIN_RST, OUTPUT);
    digitalWrite(PIN_RST, HIGH);
}

#endif // PINOUT_H
