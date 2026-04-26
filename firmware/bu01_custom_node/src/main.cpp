#include <SPI.h>
#include <DW1000Ranging.h>
#include "pinout.h"

// Forcer USART1 sur PA10(RX) / PA9(TX) = broches U1RX / U1TX de la carte
HardwareSerial UartOut(PA10, PA9);

// =========================================================================
// CONFIGURATION DU NOEUD
// =========================================================================
// 0 = TAG (Celui branché sur l'ESP32)
// 1 = ANCHOR 0 (Fond de scène gauche)
// 2 = ANCHOR 1 (Fond de scène droit)
// 3 = ANCHOR 2 (Avant-scène)
#define NODE_MODE 0
// =========================================================================

float distances[3] = {0.0, 0.0, 0.0};
uint32_t lastPrintMs = 0;

void newRange();
void newDevice(DW1000Device* device);
void inactiveDevice(DW1000Device* device);

void setup() {
    // LED de debug
    pinMode(PA1, OUTPUT);
    digitalWrite(PA1, LOW); // Allumé pendant le boot
    
    UartOut.begin(115200);
    delay(500);
    UartOut.println("=== BU01 CUSTOM FW BOOT ===");

    initHardwarePins();
    SPI.begin();
    
    UartOut.println("[*] DW1000 init...");
    DW1000.begin(PIN_IRQ, PIN_RST);
    DW1000.select(PIN_SPI_SS);
    
    char msg[128];
    DW1000.getPrintableDeviceIdentifier(msg);
    UartOut.print("[*] DW1000 Device ID: ");
    UartOut.println(msg);

    DW1000Ranging.initCommunication(PIN_RST, PIN_SPI_SS, PIN_IRQ);
    
    DW1000Ranging.attachNewRange(newRange);
    DW1000Ranging.attachNewDevice(newDevice);
    DW1000Ranging.attachInactiveDevice(inactiveDevice);

    if (NODE_MODE == 0) {
        UartOut.println("[*] Starting as TAG...");
        DW1000Ranging.startAsTag("7D:00:22:EA:82:60:3B:9C", DW1000.MODE_LONGDATA_RANGE_LOWPOWER);
    } else {
        char mac_addr[24];
        sprintf(mac_addr, "01:00:5B:D5:A9:9A:E2:%02X", NODE_MODE);
        UartOut.printf("[*] Starting as ANCHOR %d (MAC: %s)\n", NODE_MODE - 1, mac_addr);
        DW1000Ranging.startAsAnchor(mac_addr, DW1000.MODE_LONGDATA_RANGE_LOWPOWER);
    }
    
    UartOut.println("=== SETUP COMPLETE ===");
    digitalWrite(PA1, HIGH); // Eteint quand boot terminé
}

uint32_t heartbeat = 0;

void loop() {
    DW1000Ranging.loop();

    if (NODE_MODE == 0) {
        uint32_t now = millis();
        if (now - lastPrintMs >= 33) { // ~30 Hz
            lastPrintMs = now;
            heartbeat++;
            
            // Toggle LED pour montrer que la boucle tourne
            if (heartbeat % 15 == 0) {
                digitalWrite(PA1, !digitalRead(PA1));
            }
            
            // Le log d'envoi
            if (heartbeat % 90 == 0) {
                UartOut.print("[HB] alive d=[");
                UartOut.print(distances[0], 2); UartOut.print(",");
                UartOut.print(distances[1], 2); UartOut.print(",");
                UartOut.print(distances[2], 2); UartOut.println("]");
            }
            
            if (distances[0] > 0.01 || distances[1] > 0.01 || distances[2] > 0.01) {
                UartOut.print("DIST:0="); UartOut.print(distances[0], 3);
                UartOut.print(",1="); UartOut.print(distances[1], 3);
                UartOut.print(",2="); UartOut.println(distances[2], 3);
            }
        }
    }
}

void newRange() {
    if (NODE_MODE == 0) {
        uint16_t shortAddr = DW1000Ranging.getDistantDevice()->getShortAddress();
        float dist = DW1000Ranging.getDistantDevice()->getRange();
        uint8_t lastByte = shortAddr & 0xFF;
        
        if (lastByte == 1) distances[0] = dist;       // A0
        else if (lastByte == 2) distances[1] = dist;  // A1
        else if (lastByte == 3) distances[2] = dist;  // A2
    }
}

void newDevice(DW1000Device* device) {}
void inactiveDevice(DW1000Device* device) {}
