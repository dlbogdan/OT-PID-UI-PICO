import utime as time
import uasyncio as asyncio
import uos # <<<--- ADD THIS IMPORT
from hardware_config import *  # Includes init functions and constants
from controller_display import DisplayController
from gui import (  # Import the refactored components
    GUIManager, NavigationMode, EditingMode,
    Menu, IntField, FloatField, BoolField, Action, Field, IPAddressField, TextField,
    MonitoringMode, # <-- Import MonitoringMode
    Page, LogView    # <-- Import SimplePage
)
from manager_error import ErrorManager

from machine import reset
from manager_config import ConfigManager        # Config file manager
from manager_wifi import WiFiManager
from service_homematic_rpc import HomematicDataService
from controller_HID import HIDController # Import HIDController for type hint
from manager_config import factory_reset

# Assuming DEBUG is defined in flags.py or set DEVELOPMENT_MODE directly
try:
    from flags import DEBUG
    DEVELOPMENT_MODE = DEBUG
except ImportError:
    DEVELOPMENT_MODE = False # Default if flags.py doesn't exist or DEBUG isn't defined

error_manager = ErrorManager() # Global error manager


def handle_fatal_error(error_type, display, led, message, traceback=None):
    """Handles fatal errors by logging them and showing on display."""
    error_manager.log_fatal_error(error_type, message, traceback)
    try:
        if display: display.show_message("FATAL ERROR", "REBOOTING..." if not DEVELOPMENT_MODE else "ERROR")
        # Use direct_send_color as LED might not be updating anymore
        if led: led.direct_send_color("red")
    except Exception as e:
        error_manager.log_error(f"Error during fatal error handling display: {e}")
    time.sleep(2)
    if not DEVELOPMENT_MODE:
        reset()
    else:
        print(f"--- FATAL ERROR (Dev Mode) ---")
        print(f"Type: {error_type}")
        print(f"Message: {message}")
        if traceback:
            print("Traceback:", traceback)
        print("--- Halting ---")
        # Halt execution in dev mode
        while True: time.sleep(1)


async def wifi_update(wifi_service: WiFiManager):
    """Asynchronous function to update WiFi connection status."""
    while True:
        try:
            wifi_service.update()
        except Exception as e:
            error_manager.log_error(f"Error in wifi_update: {e}")
        await asyncio.sleep(5) # Check WiFi status every 5 seconds

# gui_update is no longer needed, GUIManager handles rendering via events/modes

# input_update is no longer needed, GUIManager handles input via observer pattern

async def led_update(led):
    """Asynchronous function to update LED state."""
    while True:
        try:
            led.update()
        except Exception as e:
            error_manager.log_error(f"Error in led_update: {e}")
        await asyncio.sleep_ms(100) # Update LED state relatively frequently

async def hm_data_update(homematic_service: HomematicDataService):
    """Asynchronous function to update Homematic data."""
    while True:
        try:
             # update() now decides *when* to fetch based on internal timer and paused state
            homematic_service.update()
        except Exception as e:
            error_manager.log_error(f"Error in hm_data_update: {e}")
        await asyncio.sleep(5) # Check if fetch is needed every 5 seconds

async def safe_task(coro, display, led):
    """Wraps a coroutine to catch fatal errors."""
    try:
        await coro
    except asyncio.CancelledError:
        print("Task cancelled.") # Normal cancellation
    except Exception as e:
        import sys
        # Use the global display/led references in case they aren't passed correctly
        # or the error happens before they are fully initialized in the calling context.
        handle_fatal_error("TaskError", _g_display, _g_led, str(e), sys.print_exception(e))


async def printout_hm_data(homematic_service: HomematicDataService):
    """Prints out the Homematic data periodically for debugging."""
    while True:
        if homematic_service.is_ccu_connected():
            print("--- HM Data ---")
            print(f"  Total devices: {homematic_service.total_devices}")
            print(f"  Valve devices: {homematic_service.valve_devices}")
            print(f"  Reporting valves: {homematic_service.reporting_valves}")
            print(f"  Average valve: {homematic_service.avg_valve:.1f}%")
            print(f"  Max valve: {homematic_service.max_valve:.1f}%")
            print("---------------")
        else:
            print("--- HM Data: CCU Not Connected ---")
        await asyncio.sleep(30)  # Print status less frequently


# --- NEW Task to Poll Buttons ---
async def poll_buttons(hid_controller: HIDController):
    """Periodically polls the HIDController to check for button events."""
    print("Starting button polling task...")
    while True:
        hid_controller.get_event() # This checks hardware and notifies observers if needed
        await asyncio.sleep_ms(20) # Poll reasonably fast, but yield control


async def monitor_error_rate_limiter(homematic_service: HomematicDataService, wifi_service: WiFiManager, led):
    """Monitors the error rate limiter and performs a quick reset if triggered."""
    while True:
        if error_manager.error_rate_limiter_reached:
            error_manager.log_warning("Error rate limiter TRIGGERED! Performing reset cycle.") # Log trigger

            # Pause/Disconnect services
            try:
                error_manager.log_info("Pausing Homematic service...")
                homematic_service.set_paused(True)
                error_manager.log_info("Disconnecting WiFi service...")
                wifi_service.disconnect()
            except Exception as e:
                error_manager.log_error(f"Error pausing/disconnecting services during rate limit reset: {e}")

            # Set LED to solid red briefly (visual cue)
            try:
                error_manager.log_info("Setting LED to solid red...")
                led.set_color("red", blink=False)
            except Exception as e:
                error_manager.log_error(f"Error setting LED for rate limit reset: {e}")

            # Immediately reset the limiter
            error_manager.log_info("Resetting error rate limiter flag...")
            error_manager.reset_error_rate_limiter()

            # Immediately resume services
            error_manager.log_info("Resuming services after rate limit reset...")
            homematic_service.set_paused(False)
            wifi_service.update()  # Trigger WiFi reconnection attempt

            # LED will return to normal status based on main_tasks_loop on next cycle

        # Check the limiter status periodically (e.g., every second)
        await asyncio.sleep(1)


async def main_tasks_loop(homematic_service: HomematicDataService, wifi_service: WiFiManager, led: RGBLED):
    """Main loop managing LED status based on service states."""
    # Initial LED state
    led.set_color("red", blink=False) # Start red until connections are up

    while True:
        # Update LED status based on Wifi and CCU connection
        if wifi_service.is_connected():
            homematic_service.set_paused(False) # Allow HM fetching if WiFi is up
            if homematic_service.is_ccu_connected():
                # WiFi OK, CCU OK -> Slow Green Blink
                led.set_color("green", blink=True, duration_on=50, duration_off=2000)
            else:
                # WiFi OK, CCU Not OK -> Magenta Blink (Error state)
                led.set_color("magenta", blink=True, duration_on=500, duration_off=500)
        else:
            # WiFi Not OK -> Red Blink
            homematic_service.set_paused(True) # Pause HM fetching if WiFi is down
            led.set_color("red", blink=True, duration_on=1000, duration_off=1000)

        await asyncio.sleep(1) # Check status every second
# Use global display/led for handle_fatal_error access if tasks fail early
_g_display = None
_g_led = None

# --- Monitoring Page Render Functions ---
# def render_monitor_page_1(display): ...
# def render_monitor_page_2(display): ...
# def render_monitor_page_3(display): ...

# PID Status Todo: setup these
Kp = 0.0
Ki = 0.0
Kd = 0.0
OUT = 54.0

# --- End Monitoring Pages ---

# ----------------------------

def main():
    global _g_display, _g_led
    # Remove global service variables
    # global _g_wifi_service, _g_homematic_service

    # 1. Initialize Hardware (using functions from hardware_config.py)
    try:
        i2c = init_i2c()
        mcp = init_mcp(i2c)
        lcd_hw = init_lcd(mcp) # Use a different name to avoid conflict with global 'lcd' potentially used in error handler
        led = init_rgb_led(mcp)
        buttons = init_buttons(mcp) # Returns HIDController instance
        display = DisplayController(lcd_hw) # Wrapper for LCD
        _g_display = display # Store globally for error handler
        _g_led = led       # Store globally for error handler

        # Load custom characters if defined in hardware_config
        if 'CUSTOM_CHARS' in globals():
             display.load_custom_chars(CUSTOM_CHARS)

        display.show_message("System Booting", "Please wait...")
        error_manager.log_error("Hardware reset detected.")
        led.direct_send_color("red") # Indicate booting
        print("Hardware Initialized.")

    except Exception as e:
        # Handle early hardware init errors (display/LED might not be available)
        error_message = f"FATAL: Hardware Init Failed: {e}"
        print(error_message)
        error_manager.log_fatal_error("HardwareInit", error_message)
        import sys
        # Use print_exception directly if available (MicroPython specific)
        try:
            sys.print_exception(e)
            error_manager.log_fatal_error("HardwareInit", "Traceback logged via print_exception")
        except AttributeError:
            # Fallback if print_exception doesn't exist or fails
            print("Could not print traceback.")
        # Attempt to use LED if initialized
        if '_g_led' in globals() and _g_led: _g_led.direct_send_color("red")
        # Can't use full error handler yet
        while True: time.sleep(1) # Halt

    # 2. Initialize Configuration
    try:
        config = ConfigManager("config.txt")
        ssid       = config.get_value("WIFI", "SSID")
        wifi_pass  = config.get_value("WIFI", "PASS")
        hostname   = config.get_value("WIFI", "HOSTNAME", "OT-PID-UI-PICO")
        ccu_ip     = config.get_value("CCU3", "IP", "0.0.0.0") # Default IP
        ccu_user   = config.get_value("CCU3", "USER", "")
        ccu_pass   = config.get_value("CCU3", "PASS", "")
        valve_type = config.get_value("CCU3", "VALVE_DEVTYPE", "HmIP-eTRV") # Default valve type
        # test_int   = int(config.get_value("TEST", "INT", 0))
        # test_float = float(config.get_value("TEST", "FLOAT", 0.0))
        # test_bool  = config.get_value("TEST", "BOOL", "False").lower() == 'true'

        print("Configuration Loaded.")

    except Exception as e:
        handle_fatal_error("ConfigError", display, led, str(e))

    # 3. Build the Menu Structure
    def save_config_callback(section, key, value):
        config.set_value(section, key, value)
        config.save_config() # Save immediately on change

    def save_and_reboot():
        display.show_message("Action", "Saving & Reboot")
        config.save_config()
        time.sleep(1)
        reset()

    try:
        # Build the list of menu items conditionally
        menu_items = [
            Menu("Network", [
                TextField("WiFi SSID", ssid, lambda v: save_config_callback("WIFI", "SSID", v)),
                TextField("WiFi Pass", wifi_pass, lambda v: save_config_callback("WIFI", "PASS", v)),
            ]),
            Menu("Homematic", [
                IPAddressField("CCU3 IP", ccu_ip, lambda v: save_config_callback("CCU3", "IP", v)),
                TextField("CCU3 User", ccu_user, lambda v: save_config_callback("CCU3", "USER", v)),
                TextField("CCU3 Pass", ccu_pass, lambda v: save_config_callback("CCU3", "PASS", v)),
                TextField("Valve Type", valve_type, lambda v: save_config_callback("CCU3", "VALVE_DEVTYPE", v)),
                Action("> Rescan", lambda: homematic_service.force_rescan()),
            ]),
            Menu("Device", [
                Action("> View Log", lambda: gui_manager.switch_mode("logview")),
                Action("> Reset Error limiter", lambda: error_manager.reset_error_rate_limiter()),
                Action("> Reboot Device", reset),
                Action("> Save & Reboot", save_and_reboot),
                Action("> Factory defaults", lambda: factory_reset(display, led, config, homematic_service)),
            ]),
        ]

        # Conditionally add the Debug menu
        if DEVELOPMENT_MODE:
            menu_items.append(
                Menu("Debug", [
                   Action("> Corrupt session_id", lambda: corrupt_hm_session()),
                   Action("> Force wifi disconnect", lambda: wifi_service.disconnect()),
                   Action("> Fake Error", lambda: error_manager.log_error("Fake Error")),
                ])
            )

        # Add non-menu items (if any were planned here - currently none in your structure)
        # Example: menu_items.append(TextField(...))

        # Create the root menu with the constructed list
        root_menu = Menu("Main Menu", menu_items)

        print("Menu Structure Built.")
    except Exception as e:
         handle_fatal_error("MenuError", display, led, str(e))

    # 4. Initialize Services (BEFORE Monitor Mode needs them)
    try:
        ccu_url = f"http://{ccu_ip}/api/homematic.cgi" # Use configured IP
        wifi_service = WiFiManager(ssid, wifi_pass, hostname)
        homematic_service = HomematicDataService(ccu_url, ccu_user, ccu_pass, valve_type)
        # Remove global assignments
        # _g_wifi_service = wifi_service
        # _g_homematic_service = homematic_service

        print("Services Initialized.")
    except Exception as e:
        handle_fatal_error("ServiceInitError", display, led, str(e))

    # --- Helper function for Debug Menu ---
    def corrupt_hm_session():
        """Intentionally corrupts the stored Homematic session ID for testing."""
        if homematic_service and hasattr(homematic_service, '_hm'):
            error_manager.log_info("DEBUG ACTION: Corrupting Homematic session ID.")
            homematic_service._hm._session_id = "invalid_session_for_debug"
            # Optional: Force update status to reflect potential disconnect
            # asyncio.create_task(homematic_service._hm._update_connection_status(None, "Manually corrupted session"))
        else:
            error_manager.log_warning("DEBUG ACTION: Could not corrupt session (homematic_service or _hm not found).")
    # --- End Helper --- 

    # 5. Initialize GUI Manager and Modes
    try:
        # GUIManager init automatically registers itself as observer with buttons device
        gui_manager = GUIManager(display, buttons)

        # Create mode instances
        nav_mode = NavigationMode(root_menu) # Pass the root menu
        edit_mode = EditingMode()
        # Instantiate MonitoringMode now that services exist
        # Pass refresh interval (e.g., 1000ms)
        monitor_mode = MonitoringMode(refresh_interval_ms=250)

        # --- Add monitor pages using SimplePage ---
        # Page 1: Network Status
        monitor_mode.add_page(Page(
            # Line 1: Network IP or Status
            lambda: f"Net: {wifi_service.get_ip() or wifi_service.get_status() or 'Unknown'}",
            # Line 2: CCU Status
            lambda: f"CCU: {
                'Connected' if homematic_service.is_ccu_connected() else 
                ('Checking...' if homematic_service.is_ccu_connected() is None else 'Offline')
            }"
        ))

        # Page 2: Valve Status
        monitor_mode.add_page(Page(
            # Line 1: Average Valve or Status
            lambda: (
                f"Avg: {homematic_service.avg_valve:.1f}%" if homematic_service.is_ccu_connected() 
                else ("Valve Status" if homematic_service.is_ccu_connected() is None else "Valve Status")
            ),
            # Line 2: Max Valve/Count or Status
            lambda: (
                f"Max: {homematic_service.max_valve:.1f}% {homematic_service.valve_devices}/{homematic_service.reporting_valves}" if homematic_service.is_ccu_connected() 
                else ("Checking CCU..." if homematic_service.is_ccu_connected() is None else "CCU Offline")
            )
        ))

        # Page 3: PID Status (using global Kp, Ki etc for now)
        monitor_mode.add_page(Page(
            lambda: f"Kp: {Kp:.2f} Ki: {Ki:.2f}",
            lambda: f"Kd: {Kd:.2f} OUT: {OUT:.2f}"
        ))

        # Page 4: Room with Max Valve Opening
        monitor_mode.add_page(Page(
            # Line 1: Room Name with Max Valve
            lambda: f"Room: {homematic_service.max_valve_room_name}",
            # Line 2: Max Valve %
            lambda: f"Max Valve: {homematic_service.max_valve:.1f}%" 
                     if homematic_service.is_ccu_connected() else "(CCU Offline)"
        ))

        # --- End adding pages ---

        # Register modes
        gui_manager.add_mode("navigation", nav_mode)
        gui_manager.add_mode("editing", edit_mode)
        gui_manager.add_mode("monitoring", monitor_mode)

        print("GUI Manager and Modes Initialized.")
    except Exception as e:
        handle_fatal_error("GUIInitError", display, led, str(e))

    # --- NEW ---

    async def log_view_task(log_view, gui_manager):
        """Task to manage the LogView mode."""
        while True:
            if gui_manager.current_mode_name == "logview":
                gui_manager.render()
            await asyncio.sleep(0.1)  # Adjust refresh rate as needed



    # Initialize LogView mode
    try:
        log_view = LogView("log.txt", display.rows, display.cols)
        gui_manager.add_mode("logview", log_view)
        print("LogView mode initialized.")
    except Exception as e:
        handle_fatal_error("LogViewInitError", display, led, str(e))

    # --- END NEW ---

    # 6. Start System
    try:
        print("Starting Event Loop...")
        # Set initial GUI mode (default to monitoring if available)
        initial_mode = "monitoring" if "monitoring" in gui_manager.modes else "navigation"
        gui_manager.switch_mode(initial_mode)

        # Start background tasks
        loop = asyncio.get_event_loop()
        loop.create_task(safe_task(poll_buttons(buttons), display, led))
        loop.create_task(safe_task(hm_data_update(homematic_service), display, led))
        loop.create_task(safe_task(wifi_update(wifi_service), display, led))
        loop.create_task(safe_task(led_update(led), display, led))
        loop.create_task(safe_task(monitor_error_rate_limiter(homematic_service, wifi_service, led), display, led))
        loop.create_task(safe_task(log_view_task(log_view, gui_manager), display, led))
        if DEVELOPMENT_MODE:
            loop.create_task(safe_task(printout_hm_data(homematic_service), display, led))
        loop.create_task(safe_task(main_tasks_loop(homematic_service, wifi_service, led), display, led))

        print("System Running.")
        loop.run_forever()  # Start the asyncio scheduler

    except KeyboardInterrupt:
        print("Keyboard Interrupt.")
    except Exception as e:
        handle_fatal_error("MainLoopError", display, led, str(e))
    finally:
        # Cleanup? (e.g., turn off display/led)
        if display: display.clear()
        if led: led.direct_send_color("black")
        print("System Shutdown.")
        asyncio.new_event_loop()  # Reset asyncio state (good practice in MicroPython)

if __name__ == "__main__":
    main()