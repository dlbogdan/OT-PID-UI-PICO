import time
import network
from managers.manager_logger import Logger


# --- WiFi Management ---
# class WiFiManager: ... (NO CHANGES NEEDED, connection check is non-blocking) ...
class WiFiManager:
    """Handles non-blocking WiFi connection and status monitoring."""
    STATUS_DISCONNECTED = 0
    STATUS_CONNECTING = 1
    STATUS_CONNECTED = 2
    STATUS_ERROR = 3 # E.g., WLAN interface init failed

    def __init__(self, ssid, password, hostname,retry_interval_ms=10000):
        self.ssid = ssid
        self.password = password
        self.hostname = hostname
        self.retry_interval_ms = retry_interval_ms
        # self._wlan = None
        self._status = WiFiManager.STATUS_DISCONNECTED
        self._last_attempt_time = 0
        self._ip_address = None
        self.error_manager = Logger()

        try:
            self._wlan = network.WLAN(network.STA_IF)
            self._wlan.active(False) # Start inactive
            network.hostname(self.hostname)
            self.error_manager.info("WiFiManager: WLAN interface initialized.")
            # Set initial status based on whether credentials are provided
            if self.ssid:
                 self._status = WiFiManager.STATUS_DISCONNECTED
                 self.error_manager.info("WiFiManager: Ready to connect.")
            else:
                 self._status = WiFiManager.STATUS_DISCONNECTED # Or maybe a dedicated NO_CREDS status?
                 self.error_manager.error("WiFiManager: No SSID configured, will remain disconnected.")

        except Exception as e:
            self.error_manager.fatal("WiFiManager Error: Failed to initialize WLAN interface", e)
            self._status = WiFiManager.STATUS_ERROR

    def _can_attempt_connect(self):
        """Checks if enough time has passed since the last connection attempt."""
        return time.ticks_diff(time.ticks_ms(), self._last_attempt_time) > self.retry_interval_ms

    def update(self):
        """Should be called periodically in the main loop to manage connection."""
        if self._status == WiFiManager.STATUS_ERROR or not self.ssid:
            return # Cannot proceed if WLAN failed or no SSID

        # Check current physical connection status
        is_physically_connected = self._wlan.isconnected()

        if self._status == WiFiManager.STATUS_CONNECTED:
            if not is_physically_connected:
                self.error_manager.error("WiFiManager: Connection lost.")
                self._status = WiFiManager.STATUS_DISCONNECTED
                self._ip_address = None
                self._wlan.active(False) # Deactivate to ensure clean reconnect
                self._last_attempt_time = time.ticks_ms() # Start retry timer
            else:
                # Still connected, maybe occasionally check IP just in case? (Optional)
                pass

        elif self._status == WiFiManager.STATUS_CONNECTING:
            if is_physically_connected:
                self._ip_address = self._wlan.ifconfig()[0]
                self.error_manager.info(f"WiFiManager: Connected. IP: {self._ip_address}")
                self._status = WiFiManager.STATUS_CONNECTED
            elif self._wlan.status() < 0 or self._wlan.status() >= 3: # Error codes like WRONG_PASSWORD, NO_AP_FOUND, CONN_FAIL
                self.error_manager.error(f"WiFiManager: Connection failed. Status code: {self._wlan.status()}. Retrying later.")
                self._status = WiFiManager.STATUS_DISCONNECTED
                self._wlan.active(False) # Deactivate
                self._last_attempt_time = time.ticks_ms() # Start retry timer
            # else: still connecting (status 1 or 2), just wait

        elif self._status == WiFiManager.STATUS_DISCONNECTED:
            if self._can_attempt_connect():
                self.error_manager.info(f"WiFiManager: Attempting to connect to '{self.ssid}'...")
                self._last_attempt_time = time.ticks_ms()
                try:
                    self._wlan.active(True)
                    self._wlan.connect(self.ssid, self.password)
                    self._status = WiFiManager.STATUS_CONNECTING
                except Exception as e:
                    self.error_manager.error(f"WiFiManager Error: Exception during connect initiation: {e}")
                    self._status = WiFiManager.STATUS_DISCONNECTED # Stay disconnected, retry later
                    self._wlan.active(False) # Ensure it's off if connect failed badly

    def is_connected(self):
        """Returns True if the WiFi is connected, False otherwise."""
        return self._status == WiFiManager.STATUS_CONNECTED

    def get_status(self):
        """Returns a string representation of the current status."""
        if self._status == WiFiManager.STATUS_CONNECTED: return "Connected"
        if self._status == WiFiManager.STATUS_CONNECTING: return "Connecting"
        if self._status == WiFiManager.STATUS_DISCONNECTED: return "Disconnected"
        if self._status == WiFiManager.STATUS_ERROR: return "Error"
        return "Unknown"

    def get_ip(self):
        """Returns the current IP address if connected, otherwise None."""
        return self._ip_address if self.is_connected() else None

    def disconnect(self):
        """Disconnects the WiFi connection."""
        if self._wlan:
            self._wlan.disconnect()
            self._wlan.active(False)
