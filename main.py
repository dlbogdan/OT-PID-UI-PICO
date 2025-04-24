"""
main.py


"""

# --------------------------------------------------------------------------- #
#  Imports
# --------------------------------------------------------------------------- #
import utime as time
import uasyncio as asyncio
import uos
# Import initialization functions
from managers.manager_logger import Logger
from flags import DEBUG
logger = Logger(DEBUG)

from initialization import initialize_hardware, initialize_services, setup_gui
# 3rd‑party / project modules

from managers.manager_otgw import OpenThermManager
from gui import GUIManager


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
        error_rate_limiter_task(hm, wifi, led),ot_manager.start()
    ):
        loop.create_task(coro)


# --------------------------------------------------------------------------- #
#  Initial OT State Setup Helper
# --------------------------------------------------------------------------- #


# def send_manual_setpoints(opentherm:OpenThermManager, cfg):
#     """Sends the manual setpoints to the OpenTherm manager."""
#     logger.info("Sending manual setpoints to OpenTherm manager...")
#     if "ot_max_heating_setpoint" in cfg:
#         opentherm.set_max_ch_setpoint(cfg["ot_max_heating_setpoint"])
#     if "ot_dhw_setpoint" in cfg:
#         opentherm.set_dhw_setpoint(cfg["ot_dhw_setpoint"])

# def set_initial_ot_state(opentherm:OpenThermManager, cfg):
#     """Sets the initial OpenTherm state based on loaded configuration."""
#     logger.info("Setting initial OpenTherm state from config...")
#         # Set initial state using manager methods after manager.start()
#     if "ot_max_heating_setpoint" in cfg:
#             opentherm.set_max_ch_setpoint(cfg["ot_max_heating_setpoint"])
#     if "ot_dhw_setpoint" in cfg:
#             opentherm.set_dhw_setpoint(cfg["ot_dhw_setpoint"])
#     if "ot_manual_heating_setpoint" in cfg:
#             opentherm.set_control_setpoint(cfg["ot_manual_heating_setpoint"])
    
#     # Set initial enabled states (after controller takeover if applicable)
#     controller_enabled = cfg.get("ot_enable_controller", False)
#     heating_enabled = cfg.get("ot_enable_heating", False)
#     dhw_enabled = cfg.get("ot_enable_dhw", False)

#     # Take control first if required
#     if controller_enabled:
#             initial_cs = cfg.get("ot_manual_heating_setpoint", 45.0) # Default if not in config
#             opentherm.take_control(initial_setpoint=initial_cs)
#             # Wait briefly to ensure control is established before setting modes? Might not be needed.
#             # await asyncio.sleep_ms(100) 

#     # Now set heating/DHW states
#     if heating_enabled:
#             opentherm.set_central_heating(True)
#     if dhw_enabled:
#             opentherm.set_hot_water_mode(1)

#     logger.info("Initial OpenTherm state commands issued.")



# --------------------------------------------------------------------------- #
#  Main Application Logic
# --------------------------------------------------------------------------- #

async def main():  # noqa: C901 (Complexity will be reduced)
    # Initialization 
    try:
        display, led, buttons, opentherm = initialize_hardware()
        cfg_mgr, cfg, wifi, homematic = initialize_services()
        gui = GUIManager(display, buttons) 
        setup_gui(gui, cfg_mgr, cfg, wifi, homematic, opentherm)
    except Exception as e: # Catch init errors
        logger.fatal("Initialization", str(e),resetmachine=not DEVELOPMENT_MODE)

    # Start Async Event Loop and Schedule Tasks
    loop = asyncio.get_event_loop()
    schedule_tasks(loop, wifi=wifi, hm=homematic, led=led, ot_manager=opentherm, hid=buttons)

    # set_initial_ot_state(opentherm, cfg) # todo: we shouldn't need this
    # Main Loop
    try:
        logger.info("Starting main event loop...")
        loop.run_forever()
    except KeyboardInterrupt:
        logger.warning("KeyboardInterrupt received, shutting down...")
    except Exception as e:
        logger.fatal("MainLoopError", str(e),resetmachine=False)
    finally:
        logger.info("Performing shutdown cleanup...")
        display.clear()
        display.show_message("System", "Shutting down...")
        # logger.info("Stopping OpenTherm Manager...")
        # await opentherm.stop()
        # logger.info("OpenTherm Manager stopped.")
        led.direct_send_color("black") # Turn off LED
        logger.info("Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
