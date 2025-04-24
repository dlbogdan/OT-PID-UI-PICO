"""
main.py


"""

# --------------------------------------------------------------------------- #
#  Imports
# --------------------------------------------------------------------------- #
import utime as time
import uasyncio as asyncio
import uos

from machine import reset

# 3rd‑party / project modules
from platform_spec import (
    HWi2c, HWMCP, HWLCD, HWRGBLed, HWButtons, HWUART,
    unique_hardware_name, CUSTOM_CHARS, ConfigFileName
)
from controllers.controller_display import DisplayController
from controllers.controller_HID import HIDController
from controllers.controller_otgw import OpenThermController
from managers.manager_otgw import OpenThermManager
from gui import (
    GUIManager, NavigationMode, EditingMode,
    Menu, FloatField, BoolField, Action, IPAddressField, TextField,
    MonitoringMode, Page, LogView,
)
from managers.manager_config import ConfigManager, factory_reset
from managers.manager_wifi import WiFiManager
from services.service_homematic_rpc import HomematicDataService

# Import tasks from the new file
from main_tasks import (
    wifi_task, led_task, homematic_task, poll_buttons_task,
    error_rate_limiter_task, main_status_task
)


# Keep necessary imports
from gui import GUIManager # Needed to instantiate before passing to setup_gui
from flags import DEBUG

# Import initialization functions
from initialization import (
    initialize_hardware, initialize_services, setup_gui, logger
)

# Import tasks from the new file
from main_tasks import (
    wifi_task, led_task, homematic_task, poll_buttons_task,
    error_rate_limiter_task, main_status_task
)

DEVELOPMENT_MODE=1

# --------------------------------------------------------------------------- #
#  Globals & runtime state
# --------------------------------------------------------------------------- #
# error_manager = ErrorManager()
# global error_manager

# Placeholder PID constants used by one of the monitoring pages
Kp, Ki, Kd, OUT = 0.0, 0.0, 0.0, 54.0




# --------------------------------------------------------------------------- #
#  Background task registration
# --------------------------------------------------------------------------- #

def schedule_tasks(loop, *, wifi, hm, led, ot_manager, hid):
    # Tasks are now imported from main_tasks.py
    for coro in (
        wifi_task(wifi), led_task(led), homematic_task(hm),
        poll_buttons_task(hid), main_status_task(hm, wifi, led),
        error_rate_limiter_task(hm, wifi, led),
    ):
        loop.create_task(coro)


# --------------------------------------------------------------------------- #
#  Initial OT State Setup Helper
# --------------------------------------------------------------------------- #

def set_initial_ot_state(logger, ot_manager, cfg):
    """Sets the initial OpenTherm state based on loaded configuration."""
    logger.info("Setting initial OpenTherm state from config...")
    try:
        # Set initial state using manager methods after manager.start()
        if "ot_max_heating_setpoint" in cfg:
             ot_manager.set_max_ch_setpoint(cfg["ot_max_heating_setpoint"])
        if "ot_dhw_setpoint" in cfg:
             ot_manager.set_dhw_setpoint(cfg["ot_dhw_setpoint"])
        if "ot_manual_heating_setpoint" in cfg:
             ot_manager.set_control_setpoint(cfg["ot_manual_heating_setpoint"])
        
        # Set initial enabled states (after controller takeover if applicable)
        controller_enabled = cfg.get("ot_enable_controller", False)
        heating_enabled = cfg.get("ot_enable_heating", False)
        dhw_enabled = cfg.get("ot_enable_dhw", False)

        # Take control first if required
        if controller_enabled:
             initial_cs = cfg.get("ot_manual_heating_setpoint", 45.0) # Default if not in config
             ot_manager.take_control(initial_setpoint=initial_cs)
             # Wait briefly to ensure control is established before setting modes? Might not be needed.
             # await asyncio.sleep_ms(100) 

        # Now set heating/DHW states
        if heating_enabled:
             ot_manager.set_central_heating(True)
        if dhw_enabled:
             ot_manager.set_hot_water_mode(1)

        # If controller is NOT enabled, ensure heating/DHW are off per manager logic
        # (Assuming relinquish_control or initial state handles this)
        # if not controller_enabled:
        #      ot_manager.set_central_heating(False)
        #      ot_manager.set_hot_water_mode(0)

        logger.info("Initial OpenTherm state commands issued.")

    except Exception as e:
        # Use the imported handle_fatal_error
        # We might want to allow continuation or handle this differently than a fatal error
        logger.fatal("OTStateInit", f"Error during initial OT state setup: {e}") 
        # Re-raise or return an error status if needed


# --------------------------------------------------------------------------- #
#  Main Application Logic
# --------------------------------------------------------------------------- #

async def main():  # noqa: C901 (Complexity will be reduced)
    # display, led = None, None # Define upfront for use in fatal error handler
    # ot_manager = None # Define for finally block

    try:
        # Phase 1: Hardware Initialization
        display, led, buttons = initialize_hardware()

        # Phase 2: Services Initialization
        # Pass ot_controller returned from hardware init
        cfg_mgr, cfg, wifi, hm, ot_manager = initialize_services()

        # Phase 3: GUI Manager Initialization (needs display, buttons from hardware init)
        gui = GUIManager(display, buttons) # Pass logger

        # Phase 4: GUI Setup (menu, modes, pages)
        # Pass initialized components
        setup_gui(gui, cfg_mgr, cfg, wifi, hm, ot_manager)

    except Exception as e: # Catch init errors
        # Use imported handler. Pass logger and DEVELOPMENT_MODE
        logger.fatal("Initialization", str(e))
        return # Stop execution if initialization fails

    # Phase 5: Start Async Event Loop and Schedule Tasks
    loop = asyncio.get_event_loop()
    schedule_tasks(loop, wifi=wifi, hm=hm, led=led, ot_manager=ot_manager, hid=buttons)

    # Phase 6: Start OpenTherm Manager and Set Initial State
    try:
        logger.info("Starting OpenTherm Manager...")

        loop.run_until_complete(ot_manager.start())
        logger.info("OpenTherm Manager started.")

        # Set initial state AFTER manager is started
        set_initial_ot_state(logger, ot_manager, cfg)

    except Exception as e:
        # Use imported handler. Pass logger and DEVELOPMENT_MODE
        logger.fatal("ManagerStart", str(e))
        return

    # Phase 7: Run Main Loop
    try:
        logger.info("Starting main event loop...")
        loop.run_forever()
    except KeyboardInterrupt:
        logger.warning("KeyboardInterrupt received, shutting down...")
    except Exception as e:
        logger.error(f"Unhandled exception in main loop: {e}")
        # Use imported handler. Pass logger and DEVELOPMENT_MODE
        logger.fatal("MainLoopError", str(e))
    finally:
        # Phase 8: Cleanup
        logger.info("Performing shutdown cleanup...")
        if display:
            try:
                display.clear()
                display.show_message("System", "Shutting down...")
            except Exception as e:
                 logger.error(f"Display cleanup error: {e}")
        
        if ot_manager:
            logger.info("Stopping OpenTherm Manager...")
            try:
                # Assuming ot_manager.stop() is synchronous or handles its own async shutdown
                # loop = asyncio.get_event_loop() # Loop might already be stopped
                # loop.run_until_complete(ot_manager.stop()) # Adjust if needed
                await ot_manager.stop()
                logger.info("OpenTherm Manager stopped.")
            except Exception as e:
                logger.error(f"OpenTherm Manager stop error: {e}")

        if led:
            try:
                led.direct_send_color("off") # Turn off LED
            except Exception as e:
                 logger.error(f"LED cleanup error: {e}")

        # Consider stopping other tasks gracefully if necessary
        # asyncio.new_event_loop() # Not usually needed here
        logger.info("Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
