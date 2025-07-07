#include <Arduino.h>
#include <NimBLEDevice.h>

// BLE Server Configuration
NimBLEServer* pServer = NULL;
NimBLECharacteristic* pTorqueCharacteristic = NULL;
bool deviceConnected = false;
bool oldDeviceConnected = false;

// Custom UUIDs for your torque sensor
#define SERVICE_UUID        "12345678-1234-1234-1234-123456789abc"
#define CHARACTERISTIC_UUID "87654321-4321-4321-4321-cba987654321"

// Array of predefined torque values
int torqueArray[] = {45, 85, 120, 165, 200, 175, 130, 90, 60, 30};
int arraySize = sizeof(torqueArray) / sizeof(torqueArray[0]);
int currentIndex = 0;
int currentTorque = 0;
unsigned long lastUpdate = 0;

// Function prototypes (declare before use)
void printDeviceInfo();
void sendTorqueData();
void printTorqueArray();

class ServerCallbacks: public NimBLEServerCallbacks {
    void onConnect(NimBLEServer* pServer) {
        deviceConnected = true;
        Serial.println("✅ Device connected");
        printDeviceInfo();
    };

    void onDisconnect(NimBLEServer* pServer) {
        deviceConnected = false;
        Serial.println("❌ Device disconnected");
    }
};

void printDeviceInfo() {
    Serial.println("═══════════════════════════════════════");
    Serial.println("📋 DEVICE INFORMATION:");
    Serial.print("   📱 Device Name: ");
    Serial.println("ESP32_To");
    Serial.print("   🔗 MAC Address: ");
    Serial.println(NimBLEDevice::getAddress().toString().c_str());
    Serial.print("   🆔 Service UUID: ");
    Serial.println(SERVICE_UUID);
    Serial.print("   📊 Characteristic UUID: ");
    Serial.println(CHARACTERISTIC_UUID);
    Serial.println("═══════════════════════════════════════");
}

void printTorqueArray() {
    Serial.println("📊 TORQUE VALUES ARRAY:");
    Serial.print("   Values: [");
    for (int i = 0; i < arraySize; i++) {
        Serial.print(torqueArray[i]);
        if (i < arraySize - 1) Serial.print(", ");
    }
    Serial.println("] Ncm");
    Serial.print("   Array Size: ");
    Serial.println(arraySize);
    Serial.print("   Current Index: ");
    Serial.println(currentIndex);
    Serial.print("   Current Value: ");
    Serial.print(torqueArray[currentIndex]);
    Serial.println(" Ncm");
    Serial.println("─────────────────────────────────────");
}

void setup() {
    Serial.begin(115200);
    Serial.println("🚀 Starting ESP32 BLE Torque Sensor...");
    Serial.println("🔧 Transmitting Array of Torque Values");
    Serial.println("═══════════════════════════════════════");
    
    // Print torque array information
    printTorqueArray();
    
    // Initialize BLE
    NimBLEDevice::init("ESP32_To");
    
    // Print device info immediately after BLE init
    printDeviceInfo();
    
    // Create BLE Server
    pServer = NimBLEDevice::createServer();
    pServer->setCallbacks(new ServerCallbacks());

    // Create BLE Service
    NimBLEService *pService = pServer->createService(SERVICE_UUID);

    // Create BLE Characteristic
    pTorqueCharacteristic = pService->createCharacteristic(
        CHARACTERISTIC_UUID,
        NIMBLE_PROPERTY::READ | 
        NIMBLE_PROPERTY::WRITE | 
        NIMBLE_PROPERTY::NOTIFY
    );

    // Start the service
    pService->start();

    // Start advertising
    NimBLEAdvertising *pAdvertising = NimBLEDevice::getAdvertising();
    pAdvertising->addServiceUUID(SERVICE_UUID);
    pAdvertising->setScanResponse(false);
    pAdvertising->setMinPreferred(0x0);
    NimBLEDevice::startAdvertising();

    Serial.println("📡 BLE Torque Sensor is advertising...");
    Serial.println("🎯 Ready to transmit torque array values!");
    Serial.println("═══════════════════════════════════════");
}

void loop() {
    // Cycle through torque array every 3 seconds
    if (millis() - lastUpdate > 3000) {
        // Get current torque value from array
        currentTorque = torqueArray[currentIndex];
        
        Serial.print("🔄 Array Index: ");
        Serial.print(currentIndex);
        Serial.print(" → Torque: ");
        Serial.print(currentTorque);
        Serial.println(" Ncm");
        
        if (deviceConnected) {
            sendTorqueData();
        } else {
            Serial.println("⚠️ No BLE connection - waiting for client...");
        }
        
        // Move to next index (cycle through array)
        currentIndex = (currentIndex + 1) % arraySize;
        lastUpdate = millis();
    }

    // Handle BLE reconnection
    if (!deviceConnected && oldDeviceConnected) {
        delay(500);
        pServer->startAdvertising();
        Serial.println("🔄 Restarting BLE advertising...");
        printDeviceInfo();
        oldDeviceConnected = deviceConnected;
    }
    
    if (deviceConnected && !oldDeviceConnected) {
        oldDeviceConnected = deviceConnected;
    }

    delay(100);
}

void sendTorqueData() {
    // Convert torque value to bytes (little-endian)
    uint8_t torqueBytes[4];
    torqueBytes[0] = currentTorque & 0xFF;
    torqueBytes[1] = (currentTorque >> 8) & 0xFF;
    torqueBytes[2] = (currentTorque >> 16) & 0xFF;
    torqueBytes[3] = (currentTorque >> 24) & 0xFF;
    
    // Send data via BLE
    pTorqueCharacteristic->setValue(torqueBytes, 4);
    pTorqueCharacteristic->notify();
    
    Serial.println("📤 BLE TRANSMISSION:");
    Serial.print("   📊 Torque Value: ");
    Serial.print(currentTorque);
    Serial.println(" Ncm");
    Serial.print("   📦 Raw Bytes: [");
    for (int i = 0; i < 4; i++) {
        Serial.print("0x");
        if (torqueBytes[i] < 16) Serial.print("0");
        Serial.print(torqueBytes[i], HEX);
        if (i < 3) Serial.print(", ");
    }
    Serial.println("]");
    Serial.print("   🔗 Sent to MAC: ");
    Serial.println(NimBLEDevice::getAddress().toString().c_str());
    Serial.print("   🆔 Via UUID: ");
    Serial.println(CHARACTERISTIC_UUID);
    Serial.println("─────────────────────────────────────");
}
