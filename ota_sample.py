import uasyncio as asyncio
import utime as time
from manager_wifi import WiFiManager
from manager_config import ConfigManager
from service_ota import OTAUpdateService

# Load configuration - same approach as existing code
config = None
try:
    config = ConfigManager("config.txt")
    WIFI_SSID = config.get_value("WIFI", "SSID")
    WIFI_PASS = config.get_value("WIFI", "PASS")
except Exception as e:
    print(f"Error loading config: {e}")
    WIFI_SSID = None
    WIFI_PASS = None

# You can customize these values
OTA_USERNAME = "admin"
OTA_PASSWORD = "otaota"
OTA_PORT = 80

async def wifi_update(wifi_service):
    """Asynchronous function to update WiFi connection status."""
    while True:
        try:
            wifi_service.update()
        except Exception as e:
            print(f"Error in wifi_update: {e}")
        await asyncio.sleep(5)  # Check WiFi status every 5 seconds

async def main():
    # Set hostname to unique hardware name
    from hardware_config import unique_hardware_name
    hostname = unique_hardware_name()[:15]  # truncated to 15 characters for hostname compatibility
    
    # Initialize WiFi
    wifi_service = WiFiManager(WIFI_SSID, WIFI_PASS, hostname)
    
    # Initialize OTA service
    ota_service = OTAUpdateService(
        wifi_service=wifi_service,
        auth_username=OTA_USERNAME,
        auth_password=OTA_PASSWORD,
        port=OTA_PORT
    )
    
    # Start OTA service
    await ota_service.start()
    print(f"OTA update service started on port {OTA_PORT}")
    print(f"Connect to http://{wifi_service.get_ip() or 'device-ip'}:{OTA_PORT} with username '{OTA_USERNAME}' and password '{OTA_PASSWORD}'")
    
    # Create tasks
    loop = asyncio.get_event_loop()
    loop.create_task(wifi_update(wifi_service))
    
    # Run forever
    print("System running. Press Ctrl+C to stop.")
    while True:
        # Show connection status
        if wifi_service.is_connected():
            ip = wifi_service.get_ip()
            print(f"WiFi connected. IP: {ip}")
            print(f"OTA update URL: http://{ip}:{OTA_PORT}")
        else:
            print("WiFi disconnected. Waiting for connection...")
        
        await asyncio.sleep(30)  # Status update every 30 seconds

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Keyboard interrupt received. Exiting...")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Perform any cleanup if needed
        print("System shutdown.")

# Note: This implementation has been fixed to work properly with MicroPython by:
# 1. Using direct socket handling instead of asyncio.open_connection(sock=sock)
# 2. Properly handling non-blocking sockets with small sleep intervals
# 3. Implementing multipart form data parsing directly for file uploads 