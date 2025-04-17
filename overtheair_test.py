import uasyncio as asyncio
import utime as time
from lib.manager_wifi import WiFiManager
from lib.manager_config import ConfigManager
from lib.service_overtheair import OverTheAirService
from lib.manager_error import ErrorManager

# Create error manager for the test
error_manager = ErrorManager()

# Configuration
CONFIG_FILE = "config.txt"  # Name of the config file
DEFAULT_CONFIG = {
    "WIFI": {
        "SSID": "",
        "PASS": ""
    },
    "OTA": {
        "HOST": "http://example.com",
        "PROJECT": "my_project",
        "USER": "admin",
        "PASS": "otapassword",
        "CHECK_INTERVAL": "3600"
    }
}

# Create configuration manager
config = None
try:
    config = ConfigManager(CONFIG_FILE)
    # Read WiFi settings
    WIFI_SSID = config.get_value("WIFI", "SSID")
    WIFI_PASS = config.get_value("WIFI", "PASS")
    
    # Read OTA settings
    OTA_HOST = config.get_value("OTA", "HOST", DEFAULT_CONFIG["OTA"]["HOST"])
    OTA_PROJECT = config.get_value("OTA", "PROJECT", DEFAULT_CONFIG["OTA"]["PROJECT"])
    OTA_USER = config.get_value("OTA", "USER", DEFAULT_CONFIG["OTA"]["USER"])
    OTA_PASS = config.get_value("OTA", "PASS", DEFAULT_CONFIG["OTA"]["PASS"])
    OTA_CHECK_INTERVAL = int(config.get_value("OTA", "CHECK_INTERVAL", DEFAULT_CONFIG["OTA"]["CHECK_INTERVAL"]))
    
except Exception as e:
    error_manager.log_error(f"Error loading config: {e}")
    print("Using default configuration...")
    
    # Use defaults if config can't be loaded
    WIFI_SSID = DEFAULT_CONFIG["WIFI"]["SSID"]
    WIFI_PASS = DEFAULT_CONFIG["WIFI"]["PASS"]
    OTA_HOST = DEFAULT_CONFIG["OTA"]["HOST"]
    OTA_PROJECT = DEFAULT_CONFIG["OTA"]["PROJECT"]
    OTA_USER = DEFAULT_CONFIG["OTA"]["USER"]
    OTA_PASS = DEFAULT_CONFIG["OTA"]["PASS"]
    OTA_CHECK_INTERVAL = int(DEFAULT_CONFIG["OTA"]["CHECK_INTERVAL"])

# Files to update (main application files)
OTA_FILES = [
    "main.py",
    "lib/service_overtheair.py",
    "lib/micropython_ota.py",
]

# Function to periodically update WiFi status
async def wifi_update(wifi_service):
    """Asynchronous function to update WiFi connection status."""
    while True:
        try:
            wifi_service.update()
        except Exception as e:
            error_manager.log_error(f"Error in wifi_update: {e}")
        await asyncio.sleep(5)  # Check WiFi status every 5 seconds

# Test function to manually check for updates
async def manual_check(ota_service):
    """Manually trigger an update check when a key is pressed."""
    print("\nPress 'c' to check for updates, 'u' to apply update if available, 'q' to quit")
    while True:
        if asyncio.run(asyncio.wait_for(check_input(), 1)):
            key = await asyncio.get_event_loop().run_in_executor(None, lambda: input().lower())
            if key == 'c':
                print("Manually checking for updates...")
                update_available = await ota_service.check_for_update()
                if update_available:
                    print(f"Update available: {ota_service.get_remote_version()}")
                    print(f"Current version: {ota_service.get_current_version()}")
                else:
                    print("No update available")
            elif key == 'u':
                if ota_service.is_update_available():
                    print(f"Applying update to version {ota_service.get_remote_version()}...")
                    await ota_service.apply_update()
                else:
                    print("No update available to apply")
            elif key == 'q':
                print("Exiting...")
                return True  # Signal to quit
        await asyncio.sleep(0.1)

async def check_input():
    """Non-blocking check for input - for MicroPython compatibility."""
    return True  # In MicroPython, always return True to use input() in run_in_executor

async def main():
    print("=== OTA Update Service Test ===")
    
    # Set hostname based on hardware if available
    try:
        # Import directly from the root level which is the correct path
        import hardware_config
        hostname = hardware_config.unique_hardware_name()[:15]  # truncated to 15 chars for hostname compatibility
    except:
        import random
        hostname = f"ota-test-{random.randint(1000, 9999)}"
    
    print(f"Device hostname: {hostname}")
    
    # Check if WiFi credentials are configured
    if not WIFI_SSID:
        print("WiFi not configured. Please set SSID and password in config.txt.")
        print("Add the following to config.txt:")
        print("[WIFI]")
        print("SSID=your_wifi_name")
        print("PASS=your_wifi_password")
        return
    
    # Initialize WiFi
    print(f"Connecting to WiFi: {WIFI_SSID}")
    wifi_service = WiFiManager(WIFI_SSID, WIFI_PASS, hostname)
    
    # Initialize OTA service
    print(f"Initializing OTA service: {OTA_HOST}/{OTA_PROJECT}")
    ota_service = OverTheAirService(
        wifi_service=wifi_service,
        host=OTA_HOST,
        project=OTA_PROJECT,
        filenames=OTA_FILES,
        check_interval=OTA_CHECK_INTERVAL,
        user=OTA_USER,
        password=OTA_PASS,
        auto_update=False  # Don't auto-update in test mode
    )
    
    # Create tasks
    wifi_task = asyncio.create_task(wifi_update(wifi_service))
    
    # Start OTA service
    await ota_service.start()
    print("OTA service started")
    
    # Main loop with status updates
    print("\nSystem running. Press Ctrl+C to stop.")
    quit_requested = False
    manual_check_task = asyncio.create_task(manual_check(ota_service))
    
    while not quit_requested:
        # Show connection status
        if wifi_service.is_connected():
            ip = wifi_service.get_ip()
            print(f"WiFi connected: {ip}")
            
            # Display OTA status
            current_version = ota_service.get_current_version() or "unknown"
            if ota_service.is_update_available():
                print(f"Update available: {ota_service.get_remote_version()} (current: {current_version})")
            else:
                print(f"Current version: {current_version}, no updates available")
                
        else:
            print("WiFi disconnected. Waiting for connection...")
        
        # Check if manual check task has requested quit
        if manual_check_task.done():
            quit_requested = True
        
        await asyncio.sleep(10)  # Status update every 10 seconds
    
    # Clean up
    await ota_service.stop()
    wifi_task.cancel()
    manual_check_task.cancel()
    
    print("Test completed")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nKeyboard interrupt received. Exiting...")
    except Exception as e:
        error_manager.log_error(f"Error in main: {e}")
        print(f"Error: {e}")
    finally:
        # Perform any cleanup if needed
        print("Test shutdown completed.") 