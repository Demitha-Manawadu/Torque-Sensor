import sys
import sqlite3
import pandas as pd
import pyqtgraph as pg
import qdarkstyle
import matplotlib.pyplot as plt
import asyncio
import threading
import traceback
from bleak import BleakClient, BleakScanner
from PyQt6.QtWidgets import (QApplication, QMainWindow, QPushButton, QLabel, 
                           QVBoxLayout, QWidget, QSlider, QSplitter, QTextEdit)
from PyQt6.QtCore import QTimer, Qt, pyqtSignal, QObject
from reportlab.pdfgen import canvas
from datetime import datetime

# BLE Configuration
SENSOR_ADDRESS = None
SERVICE_UUID = "12345678-1234-1234-1234-123456789abc"
CHARACTERISTIC_UUID = "87654321-4321-4321-4321-cba987654321"

# Database Configuration
DB_FILE = "torque_data.db"
THRESHOLD = 100

class BLESignals(QObject):
    """Signals for BLE communication"""
    data_received = pyqtSignal(int)
    connection_status = pyqtSignal(str)
    device_found = pyqtSignal(str, str)
    error_occurred = pyqtSignal(str)
    scan_completed = pyqtSignal(bool)

class TorqueDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # Application state flags
        self.app_running = True
        self.force_close = False
        
        try:
            # Initialize database
            self.init_database()
            
            # BLE signals
            self.ble_signals = BLESignals()
            self.ble_signals.data_received.connect(self.on_data_received)
            self.ble_signals.connection_status.connect(self.on_connection_status)
            self.ble_signals.device_found.connect(self.on_device_found)
            self.ble_signals.error_occurred.connect(self.on_error_occurred)
            self.ble_signals.scan_completed.connect(self.on_scan_completed)
            
            # BLE client and connection management
            self.ble_client = None
            self.is_connected = False
            self.scan_thread = None
            self.connection_thread = None
            self.connection_active = False
            
            # Array detection
            self.received_values = []
            self.array_detection_active = False
            
            # Connection retry mechanism
            self.retry_count = 0
            self.max_retries = 3
            self.auto_retry = False
            
            self.setup_ui()
            self.setup_graph()
            
            # Timer for graph updates and connection monitoring
            self.timer = QTimer()
            self.timer.timeout.connect(self.update_graph)
            self.timer.start(1000)
            
            # Connection monitor timer
            self.connection_monitor = QTimer()
            self.connection_monitor.timeout.connect(self.monitor_connection)
            self.connection_monitor.start(5000)  # Check every 5 seconds
            
            self.log_message("✅ Dashboard initialized successfully")
            self.log_message("🔍 Dashboard will remain open even without ESP32 connection")
            
        except Exception as e:
            print(f"❌ Initialization error: {e}")
            traceback.print_exc()
            # Don't close the application, just log the error
            if hasattr(self, 'log_message'):
                self.log_message(f"❌ Initialization error: {e}")

    def closeEvent(self, event):
        """Handle application close event"""
        if not self.force_close:
            self.log_message("🔄 Dashboard closing gracefully...")
            self.app_running = False
            self.is_connected = False
            self.connection_active = False
            
            # Stop timers
            if hasattr(self, 'timer'):
                self.timer.stop()
            if hasattr(self, 'connection_monitor'):
                self.connection_monitor.stop()
            
            # Disconnect BLE if connected
            if self.ble_client and hasattr(self.ble_client, 'is_connected'):
                try:
                    if self.ble_client.is_connected:
                        self.safe_disconnect_device()
                except:
                    pass
        
        event.accept()

    def init_database(self):
        """Initialize SQLite database"""
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS torque_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    torque_value REAL
                )
            ''')
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"❌ Database initialization error: {e}")

    def setup_ui(self):
        """Setup the user interface"""
        try:
            self.setWindowTitle("🔧 ESP32 Torque Array Dashboard - Persistent Mode")
            self.setGeometry(200, 200, 1200, 800)

            # Status labels
            self.status_label = QLabel("🔍 Dashboard ready - ESP32 connection optional", self)
            self.status_label.setStyleSheet("color: #00CC66; font-size: 14px; font-weight: bold; padding: 8px;")
            
            self.torque_label = QLabel("Torque Value: No ESP32 connected (Dashboard remains active)", self)
            self.torque_label.setStyleSheet("color: #FFD700; font-size: 16px; font-weight: bold; padding: 8px;")

            # Connection status label
            self.connection_label = QLabel("Connection: Disconnected (Dashboard operational)", self)
            self.connection_label.setStyleSheet("color: #FF6B6B; font-size: 12px; padding: 8px;")

            # Error display label
            self.error_label = QLabel("Status: Ready - Dashboard will not close automatically", self)
            self.error_label.setStyleSheet("color: #FFD700; font-size: 12px; padding: 8px;")

            # Console output
            self.console = QTextEdit()
            self.console.setMaximumHeight(200)
            self.console.setStyleSheet("background-color: #1e1e1e; color: #00ff00; font-family: monospace;")
            self.console.append("=== ESP32 BLE Torque Array Dashboard - Persistent Mode ===")
            self.console.append("✅ Application started successfully")
            self.console.append("🔄 Dashboard will remain open regardless of ESP32 connection status")

            # Buttons
            self.btn_scan = QPushButton("🔍 Scan for ESP32 Devices")
            self.btn_scan.clicked.connect(self.safe_scan_devices)
            
            self.btn_connect = QPushButton("🔗 Connect to ESP32")
            self.btn_connect.clicked.connect(self.safe_connect_device)
            self.btn_connect.setEnabled(False)
            
            self.btn_disconnect = QPushButton("❌ Disconnect")
            self.btn_disconnect.clicked.connect(self.safe_disconnect_device)
            self.btn_disconnect.setEnabled(False)

            # Auto-retry checkbox
            self.btn_auto_retry = QPushButton("🔄 Toggle Auto-Retry")
            self.btn_auto_retry.clicked.connect(self.toggle_auto_retry)
            self.btn_auto_retry.setStyleSheet("background-color: #444444;")

            # Simulate data button (for testing without ESP32)
            self.btn_simulate = QPushButton("🎲 Simulate Torque Data")
            self.btn_simulate.clicked.connect(self.simulate_torque_data)

            # Threshold slider
            self.slider_threshold = QSlider(Qt.Orientation.Horizontal)
            self.slider_threshold.setMinimum(10)
            self.slider_threshold.setMaximum(200)
            self.slider_threshold.setValue(THRESHOLD)
            self.slider_threshold.valueChanged.connect(self.update_threshold)
            self.threshold_label = QLabel(f"⚠️ Alert Threshold: {THRESHOLD} Ncm")

            # Export buttons
            self.btn_export_csv = QPushButton("📄 Export CSV")
            self.btn_export_csv.clicked.connect(self.export_csv)
            
            self.btn_history = QPushButton("📊 View History")
            self.btn_history.clicked.connect(self.plot_history)
            
            self.btn_theme = QPushButton("🌙 Toggle Theme")
            self.btn_theme.clicked.connect(self.toggle_theme)

            self.btn_force_close = QPushButton("❌ Force Close Dashboard")
            self.btn_force_close.clicked.connect(self.force_close_app)
            self.btn_force_close.setStyleSheet("background-color: #8B0000; color: white;")

            # Layout
            layout = QVBoxLayout()
            layout.addWidget(self.status_label)
            layout.addWidget(self.connection_label)
            layout.addWidget(self.error_label)
            layout.addWidget(self.torque_label)
            layout.addWidget(self.console)
            layout.addWidget(self.btn_scan)
            layout.addWidget(self.btn_connect)
            layout.addWidget(self.btn_disconnect)
            layout.addWidget(self.btn_auto_retry)
            layout.addWidget(self.btn_simulate)
            layout.addWidget(self.threshold_label)
            layout.addWidget(self.slider_threshold)
            layout.addWidget(self.btn_export_csv)
            layout.addWidget(self.btn_history)
            layout.addWidget(self.btn_theme)
            layout.addWidget(self.btn_force_close)

            container = QWidget()
            container.setLayout(layout)
            
            self.setCentralWidget(container)
            
            # Apply dark theme safely
            try:
                self.setStyleSheet(qdarkstyle.load_stylesheet_pyqt6())
            except:
                self.log_message("⚠️ Dark theme not available, using default theme")
                
        except Exception as e:
            print(f"❌ UI setup error: {e}")
            traceback.print_exc()

    def setup_graph(self):
        """Setup the real-time graph"""
        try:
            self.graph = pg.PlotWidget()
            self.graph.setBackground('black')
            self.graph.setTitle("Real-Time Torque Array Values", color="white", size="14pt")
            self.graph.setLabel('left', 'Torque (Ncm)', color='white')
            self.graph.setLabel('bottom', 'Time', color='white')
            self.graph.showGrid(x=True, y=True, alpha=0.3)
            
            # Add graph to layout
            layout = self.centralWidget().layout()
            layout.insertWidget(4, self.graph)
        except Exception as e:
            self.log_message(f"❌ Graph setup error: {e}")

    def log_message(self, message):
        """Add message to console safely"""
        try:
            if hasattr(self, 'console'):
                timestamp = datetime.now().strftime("%H:%M:%S")
                self.console.append(f"[{timestamp}] {message}")
        except Exception as e:
            print(f"Console error: {e}")

    def monitor_connection(self):
        """Monitor connection status and handle disconnections gracefully"""
        if not self.app_running:
            return
            
        try:
            if self.is_connected and self.ble_client:
                if not self.ble_client.is_connected:
                    self.log_message("⚠️ ESP32 connection lost - Dashboard remains active")
                    self.is_connected = False
                    self.connection_active = False
                    self.update_connection_status("disconnected")
                    
                    if self.auto_retry and self.retry_count < self.max_retries:
                        self.log_message(f"🔄 Auto-retry attempt {self.retry_count + 1}/{self.max_retries}")
                        self.retry_count += 1
                        self.safe_connect_device()
            
            # Update UI to show dashboard is still active
            if not self.is_connected:
                self.connection_label.setText("Connection: Disconnected (Dashboard operational)")
                self.connection_label.setStyleSheet("color: #FF6B6B; font-size: 12px; padding: 8px;")
                
        except Exception as e:
            # Don't crash on connection monitoring errors
            self.log_message(f"⚠️ Connection monitor error: {e}")

    def on_error_occurred(self, error_message):
        """Handle errors safely without closing dashboard"""
        try:
            self.error_label.setText(f"⚠️ Error: {error_message} (Dashboard remains active)")
            self.error_label.setStyleSheet("color: #FFA500; font-size: 12px; padding: 8px;")
            self.log_message(f"⚠️ {error_message}")
            
            # Reset connection state but keep dashboard open
            self.is_connected = False
            self.connection_active = False
            self.btn_connect.setEnabled(True)
            self.btn_disconnect.setEnabled(False)
            
        except Exception as e:
            print(f"Error handling error: {e}")

    def safe_scan_devices(self):
        """Safely start BLE device scanning"""
        try:
            self.log_message("🔍 Starting BLE scan...")
            self.btn_scan.setEnabled(False)
            self.btn_scan.setText("⏳ Scanning...")
            
            # Kill existing scan thread if running
            if self.scan_thread and self.scan_thread.is_alive():
                self.log_message("⚠️ Stopping previous scan...")
            
            # Start new scan thread
            self.scan_thread = threading.Thread(target=self.run_scan_safe)
            self.scan_thread.daemon = True
            self.scan_thread.start()
            
        except Exception as e:
            self.ble_signals.error_occurred.emit(f"Scan start error: {e}")
            self.btn_scan.setEnabled(True)
            self.btn_scan.setText("🔍 Scan for ESP32 Devices")

    def run_scan_safe(self):
        """Run BLE scan safely in separate thread"""
        try:
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Run the scan with timeout
            loop.run_until_complete(asyncio.wait_for(self.scan_ble_devices_safe(), timeout=15.0))
            
        except asyncio.TimeoutError:
            self.ble_signals.error_occurred.emit("Scan timeout - ESP32 may not be available")
            self.ble_signals.scan_completed.emit(False)
        except Exception as e:
            self.ble_signals.error_occurred.emit(f"Scan error: {e}")
            self.ble_signals.scan_completed.emit(False)
        finally:
            self.ble_signals.scan_completed.emit(True)

    async def scan_ble_devices_safe(self):
        """Scan for BLE devices safely"""
        try:
            self.log_message("🔍 Scanning for BLE devices...")
            devices = await BleakScanner.discover(timeout=10.0)
            found_esp32 = False
            
            self.log_message(f"📡 Found {len(devices)} BLE devices")
            
            for device in devices:
                try:
                    device_name = device.name or "Unknown"
                    self.log_message(f"Found: {device_name} ({device.address})")
                    
                    if device_name and ("ESP32_To" in device_name):
                        self.ble_signals.device_found.emit(device.address, device_name)
                        found_esp32 = True
                        break
                except Exception as e:
                    continue
            
            if not found_esp32:
                self.log_message("❌ No ESP32_To devices found - Dashboard remains active")
                
        except Exception as e:
            self.ble_signals.error_occurred.emit(f"BLE scan failed: {e}")

    def on_scan_completed(self, success):
        """Handle scan completion"""
        self.btn_scan.setEnabled(True)
        self.btn_scan.setText("🔍 Scan for ESP32 Devices")
        if not success:
            self.log_message("🔍 Scan completed - No ESP32 found, but dashboard remains active")

    def on_device_found(self, address, name):
        """Handle ESP32 device found"""
        global SENSOR_ADDRESS
        SENSOR_ADDRESS = address
        self.log_message(f"✅ ESP32 found: {name} at {address}")
        self.status_label.setText(f"✅ ESP32 Found: {address}")
        self.btn_connect.setEnabled(True)
        self.retry_count = 0  # Reset retry count on successful discovery

    def safe_connect_device(self):
        """Safely connect to ESP32 device"""
        try:
            if not SENSOR_ADDRESS:
                self.ble_signals.error_occurred.emit("No ESP32 address available - Please scan first")
                return
                
            self.log_message(f"🔗 Attempting connection to {SENSOR_ADDRESS}...")
            self.btn_connect.setEnabled(False)
            self.btn_connect.setText("⏳ Connecting...")
            self.connection_active = True
            
            # Start connection thread
            self.connection_thread = threading.Thread(target=self.run_connection_safe)
            self.connection_thread.daemon = True
            self.connection_thread.start()
            
        except Exception as e:
            self.ble_signals.error_occurred.emit(f"Connection start error: {e}")

    def run_connection_safe(self):
        """Run BLE connection safely"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Run connection with timeout
            loop.run_until_complete(asyncio.wait_for(self.connect_ble_device_safe(), timeout=30.0))
            
        except asyncio.TimeoutError:
            self.ble_signals.error_occurred.emit("Connection timeout - ESP32 may not be responding")
            self.ble_signals.connection_status.emit("failed")
        except Exception as e:
            self.ble_signals.error_occurred.emit(f"Connection error: {e}")
            self.ble_signals.connection_status.emit("failed")

    async def connect_ble_device_safe(self):
        """Connect to BLE device safely"""
        try:
            self.ble_client = BleakClient(SENSOR_ADDRESS)
            await self.ble_client.connect()
            
            if self.ble_client.is_connected:
                self.ble_signals.connection_status.emit("connected")
                
                # Start reading data loop
                while (self.ble_client.is_connected and 
                       self.is_connected and 
                       self.connection_active and 
                       self.app_running):
                    try:
                        value = await self.ble_client.read_gatt_char(CHARACTERISTIC_UUID)
                        torque_value = int.from_bytes(value, byteorder="little")
                        self.ble_signals.data_received.emit(torque_value)
                        await asyncio.sleep(2.5)
                    except Exception as e:
                        self.ble_signals.error_occurred.emit(f"Data read error: {e}")
                        break
            else:
                self.ble_signals.connection_status.emit("failed")
                
        except Exception as e:
            self.ble_signals.error_occurred.emit(f"BLE connection failed: {e}")
            self.ble_signals.connection_status.emit("failed")

    def update_connection_status(self, status):
        """Update connection status in UI"""
        if status == "connected":
            self.connection_label.setText("Connection: ✅ Connected to ESP32")
            self.connection_label.setStyleSheet("color: #00CC66; font-size: 12px; padding: 8px;")
        elif status == "disconnected":
            self.connection_label.setText("Connection: ❌ Disconnected (Dashboard remains active)")
            self.connection_label.setStyleSheet("color: #FF6B6B; font-size: 12px; padding: 8px;")

    def on_connection_status(self, status):
        """Handle connection status changes"""
        if status == "connected":
            self.is_connected = True
            self.connection_active = True
            self.log_message("✅ Connected to ESP32!")
            self.status_label.setText("✅ Connected - Receiving Data")
            self.update_connection_status("connected")
            self.btn_connect.setEnabled(False)
            self.btn_connect.setText("🔗 Connect to ESP32")
            self.btn_disconnect.setEnabled(True)
            self.retry_count = 0
        elif status == "failed":
            self.is_connected = False
            self.connection_active = False
            self.log_message("❌ Connection failed - Dashboard remains active")
            self.update_connection_status("disconnected")
            self.btn_connect.setEnabled(True)
            self.btn_connect.setText("🔗 Connect to ESP32")
            self.btn_disconnect.setEnabled(False)

    def safe_disconnect_device(self):
        """Safely disconnect from ESP32"""
        try:
            self.is_connected = False
            self.connection_active = False
            self.log_message("❌ Disconnecting from ESP32...")
            self.update_connection_status("disconnected")
            self.btn_disconnect.setEnabled(False)
            self.btn_connect.setEnabled(True)
            
            if self.ble_client:
                # Disconnect in background thread
                disconnect_thread = threading.Thread(target=self.run_disconnect_safe)
                disconnect_thread.daemon = True
                disconnect_thread.start()
                
        except Exception as e:
            self.ble_signals.error_occurred.emit(f"Disconnect error: {e}")

    def run_disconnect_safe(self):
        """Run disconnect safely"""
        try:
            if self.ble_client and hasattr(self.ble_client, 'disconnect'):
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self.ble_client.disconnect())
        except Exception as e:
            self.log_message(f"⚠️ Disconnect error: {e}")

    def toggle_auto_retry(self):
        """Toggle auto-retry connection feature"""
        self.auto_retry = not self.auto_retry
        if self.auto_retry:
            self.btn_auto_retry.setText("🔄 Auto-Retry: ON")
            self.btn_auto_retry.setStyleSheet("background-color: #006600; color: white;")
            self.log_message("✅ Auto-retry enabled")
        else:
            self.btn_auto_retry.setText("🔄 Auto-Retry: OFF")
            self.btn_auto_retry.setStyleSheet("background-color: #444444; color: white;")
            self.log_message("❌ Auto-retry disabled")

    def simulate_torque_data(self):
        """Simulate torque data for testing without ESP32"""
        import random
        simulated_values = [45, 85, 120, 165, 200, 175, 130, 90, 60, 30]
        value = random.choice(simulated_values)
        self.ble_signals.data_received.emit(value)
        self.log_message(f"🎲 Simulated torque: {value} Ncm")

    def on_data_received(self, torque_value):
        """Handle received torque data"""
        try:
            self.save_torque_value(torque_value)
            self.log_message(f"📊 Received: {torque_value} Ncm")
            
            # Update torque label
            if torque_value > THRESHOLD:
                self.torque_label.setStyleSheet("color: red; font-size: 16px; font-weight: bold;")
                self.torque_label.setText(f"⚠️ HIGH TORQUE: {torque_value} Ncm")
            else:
                self.torque_label.setStyleSheet("color: green; font-size: 16px; font-weight: bold;")
                self.torque_label.setText(f"✅ Torque: {torque_value} Ncm")
                
        except Exception as e:
            self.ble_signals.error_occurred.emit(f"Data handling error: {e}")

    def save_torque_value(self, torque_value):
        """Save torque value to database"""
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO torque_data (torque_value) VALUES (?)", (torque_value,))
            conn.commit()
            conn.close()
        except Exception as e:
            self.log_message(f"❌ Database save error: {e}")

    def update_graph(self):
        """Update the real-time graph"""
        try:
            if not self.app_running:
                return
                
            conn = sqlite3.connect(DB_FILE)
            df = pd.read_sql("SELECT * FROM torque_data ORDER BY timestamp DESC LIMIT 50", conn)
            conn.close()

            if not df.empty:
                latest_value = df.iloc[0]["torque_value"]
                
                self.graph.clear()
                times = list(range(len(df)))
                values = df["torque_value"].tolist()
                
                color = 'red' if latest_value > THRESHOLD else 'green'
                self.graph.plot(times, values, pen=pg.mkPen(color, width=2), symbol='o', symbolSize=4)
                self.graph.addLine(y=THRESHOLD, pen=pg.mkPen('yellow', width=1, style=Qt.PenStyle.DashLine))
            else:
                # Show empty graph with threshold line
                self.graph.clear()
                self.graph.addLine(y=THRESHOLD, pen=pg.mkPen('yellow', width=1, style=Qt.PenStyle.DashLine))
                
        except Exception as e:
            # Silently handle graph errors to prevent crashes
            pass

    def update_threshold(self):
        """Update threshold value"""
        global THRESHOLD
        THRESHOLD = self.slider_threshold.value()
        self.threshold_label.setText(f"⚠️ Alert Threshold: {THRESHOLD} Ncm")

    def export_csv(self):
        """Export data to CSV"""
        try:
            conn = sqlite3.connect(DB_FILE)
            df = pd.read_sql("SELECT * FROM torque_data ORDER BY timestamp DESC", conn)
            conn.close()
            
            if df.empty:
                self.log_message("⚠️ No data to export")
                return
            
            filename = f"torque_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            df.to_csv(filename, index=False)
            self.log_message(f"✅ Data exported to {filename}")
        except Exception as e:
            self.log_message(f"❌ Export failed: {e}")

    def plot_history(self):
        """Plot historical data"""
        try:
            conn = sqlite3.connect(DB_FILE)
            df = pd.read_sql("SELECT * FROM torque_data ORDER BY timestamp ASC", conn)
            conn.close()
            
            if df.empty:
                self.log_message("⚠️ No data to plot - Use 'Simulate Torque Data' to generate test data")
                return
            
            plt.figure(figsize=(10, 6))
            plt.plot(df.index, df['torque_value'], 'g-', linewidth=2)
            plt.axhline(y=THRESHOLD, color='r', linestyle='--', label=f'Threshold ({THRESHOLD})')
            plt.title('Torque Values Over Time')
            plt.ylabel('Torque (Ncm)')
            plt.xlabel('Reading Number')
            plt.legend()
            plt.grid(True, alpha=0.3)
            plt.show()
            
        except Exception as e:
            self.log_message(f"❌ Plot failed: {e}")

    def toggle_theme(self):
        """Toggle between light and dark themes"""
        try:
            current_style = self.styleSheet()
            if "dark" in current_style.lower():
                self.setStyleSheet("")
                self.log_message("🌞 Light theme")
            else:
                self.setStyleSheet(qdarkstyle.load_stylesheet_pyqt6())
                self.log_message("🌙 Dark theme")
        except Exception as e:
            self.log_message(f"❌ Theme change failed: {e}")

    def force_close_app(self):
        """Force close the application"""
        self.log_message("🔴 Force closing dashboard...")
        self.force_close = True
        self.app_running = False
        self.close()

def main():
    """Main application entry point with enhanced error handling"""
    try:
        # Create QApplication
        app = QApplication(sys.argv)
        
        # Set application properties
        app.setApplicationName("ESP32 Torque Dashboard - Persistent")
        app.setApplicationVersion("2.0")
        
        # Create and show main window
        window = TorqueDashboard()
        window.show()
        
        print("✅ Dashboard started successfully")
        print("🔍 Dashboard will remain open even without ESP32 connection")
        print("🔄 Use the dashboard buttons to connect to ESP32 when available")
        
        # Run the application
        sys.exit(app.exec())
        
    except Exception as e:
        print(f"❌ Application startup failed: {e}")
        traceback.print_exc()
        print("🔄 Attempting to keep console open...")
        input("Press Enter to exit...")

if __name__ == "__main__":
    main()
