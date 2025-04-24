# mqtt_test.py
import uasyncio as asyncio
import utime as time
import machine
import ubinascii
import gc

# Import WiFi Manager and Config Manager
from managers.manager_wifi import WiFiManager
from managers.manager_config import ConfigManager

# Assuming service_mqtt.py is in the same directory or /lib

from services.boilerhaentity import BoilerController


# Load configuration
config = None
try:
    if ConfigManager is not None:
        config = ConfigManager("config.txt")
        WIFI_SSID = config.get_value("WIFI", "SSID")
        WIFI_PASS = config.get_value("WIFI", "PASS")
    else:
        WIFI_SSID = None
        WIFI_PASS = None
except Exception as e:
    print(f"Error loading config: {e}")
    WIFI_SSID = None
    WIFI_PASS = None

# --- MQTT Configuration --- (!!! REPLACE WITH YOUR DETAILS !!!)
MQTT_BROKER = "10.9.30.11" # e.g., "192.168.1.100" or "test.mosquitto.org"
MQTT_PORT = 1883
MQTT_USER = "mqtt"  # Set to your username if required, e.g., "mqtt_user"
MQTT_PASSWORD = "11c244f3508fd720661dd69aa1f5c31c" # Set to your password if required, e.g., "mqtt_password"
# ---------------------

async def wifi_update(wifi_service):
    """Asynchronous function to update WiFi connection status."""
    while True:
        try:
            wifi_service.update()
        except Exception as e:
            print(f"Error in wifi_update: {e}")
        await asyncio.sleep(5) # Check WiFi status every 5 seconds

async def main():
    # Check for required services
    
    if None in (WIFI_SSID, WIFI_PASS):
        print("WiFi credentials not configured in config.txt. Please edit the file.")
        return


    # Initialize WiFi
    print("Initializing WiFi...")
    if WiFiManager is None:
        print("WiFiManager not available. Exiting.")
        return
    wifi_service = WiFiManager(WIFI_SSID, WIFI_PASS, f"mqtt-test")
    
    # Create and start WiFi update task
    wifi_task = asyncio.create_task(wifi_update(wifi_service))
    print("WiFi update task created.")

    # Wait for initial WiFi connection
    print("Waiting for WiFi connection...")
    while not wifi_service.is_connected():
        await asyncio.sleep(1)
    print(f"WiFi connected! IP: {wifi_service.get_ip()}")

    # Instantiate the MQTT Service
    # Using print for error callback for simplicity in this test file
    


    boiler = BoilerController(mqtt_broker=MQTT_BROKER, device_id="boiler-test", base_topic="mydevice/boiler", mqtt_user=MQTT_USER, mqtt_pass=MQTT_PASSWORD)

    asyncio.create_task(boiler.start())


    # --- Main Test Loop ---
    counter = 0
    last_config_publish_time = time.ticks_ms()

    while True:
        gc.collect() # Collect garbage periodically

        # 1. Check Connection Status (Informational)
        # is_connected = mqtt_service.is_connected()
        # print(f"Loop {counter} | MQTT Connected: {is_connected} | WiFi Connected: {wifi_service.is_connected()} | Mem Free: {gc.mem_free()}")

        # # 2. Get Data from Listener Topics
        # command = mqtt_service.get(f"{base_topic}/command")
        # if command is not None and command != "": # Check for non-empty command
        #     print(f"---> Received Command: '{command}'")
        #     # Example action: Clear the command topic after processing
        #     mqtt_service.set(f"{base_topic}/command", "") # Set empty string to clear
        #     if command == "reboot":
        #         print("Reboot command received! (Simulated)")
        #         # machine.reset() # Uncomment to actually reboot

        # new_config = mqtt_service.get(f"{base_topic}/config/set")
        # if new_config is not None:
        #     print(f"---> Received New Config: {new_config}")
        #     # Update our 'current' config publisher
        #     mqtt_service.set(f"{base_topic}/config/current", new_config)

        # # 3. Set Data for Publisher Topics
        # mqtt_service.set(f"{base_topic}/counter", counter)

        # 4. Wait
        await asyncio.sleep(5) # Main loop interval
        counter += 1

# Run the main async function
if __name__ == "__main__":
    # Add a small delay before starting? Sometimes helps hardware init.
    time.sleep_ms(500)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Keyboard Interrupt, exiting test.")
    except Exception as e:
        print(f"An error occurred: {e}")
        # Optionally try a reset on other exceptions during testing
        # print("Attempting reset...")
        # time.sleep(2)
        # machine.reset()
    finally:
        # Cleanup is usually handled by asyncio.run, but good practice:
        asyncio.new_event_loop()
        print("Test finished.") 