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
from controller_pid import PIDController # Import the PID controller

# Import tasks from the new file
from main_tasks import (
    wifi_task, led_task, homematic_task, poll_buttons_task,
    error_rate_limiter_task, main_status_task,
    pid_control_task, log_pid_output_task # Import the new task
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

def schedule_tasks(loop, *, wifi, hm, led, ot_manager, hid, pid=None, interval_s=None, cfg_mgr=None):
    # Tasks are now imported from main_tasks.py
    tasks_to_schedule = [
        wifi_task(wifi), 
        led_task(led), 
        homematic_task(hm),
        poll_buttons_task(hid), 
        main_status_task(hm, wifi, led),
        error_rate_limiter_task(hm, wifi, led),
        ot_manager.start()
    ]
    # Conditionally add the PID task if it exists
    if pid is not None and interval_s is not None and cfg_mgr is not None:
        logger.info("Scheduling PID/Manual Control task.")
        tasks_to_schedule.append(pid_control_task(pid, hm, ot_manager, interval_s, cfg_mgr))
        # Schedule the new logging task
        logger.info("Scheduling PID output logging task.")
        tasks_to_schedule.append(log_pid_output_task(pid)) # Default interval is 60s
    else:
        logger.warning("PID instance or interval not available, PID task not scheduled.")
        
    for coro in tasks_to_schedule:
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
    pid_instance = None # Define outside try block
    cfg_mgr = None # Define cfg_mgr outside try block
    try:
        display, led, buttons, opentherm = initialize_hardware()
        # Correct unpacking: initialize_services now returns 3 items
        cfg_mgr, wifi, homematic = initialize_services() 
        gui = GUIManager(display, buttons) 
        
        # Instantiate PID Controller using cfg_mgr.get()
        logger.info("Instantiating PID Controller...")
        pid_instance = PIDController(
            # Use cfg_mgr.get directly - type hint in ConfigManager should help linter
            kp=cfg_mgr.get("PID", "KP", 0.05), 
            ki=cfg_mgr.get("PID", "KI", 0.002),
            kd=cfg_mgr.get("PID", "KD", 0.01),
            setpoint=cfg_mgr.get("PID", "SETPOINT", 25.0),
            output_min=35.0, # Keep hardcoded or load if needed
            output_max=cfg_mgr.get("OT", "MAX_HEATING_SETPOINT", 72.0), # Get OT max heating SP
            integral_min=None, # Keep default for now
            integral_max=None, # Keep default for now
            ff_wind_coeff=cfg_mgr.get("PID", "FF_WIND_COEFF", 0.1),
            ff_temp_coeff=cfg_mgr.get("PID", "FF_TEMP_COEFF", 1.1),
            ff_sun_coeff=cfg_mgr.get("PID", "FF_SUN_COEFF", 0.0001),
            ff_wind_interaction_coeff=cfg_mgr.get("PID", "FF_WIND_INTERACTION_COEFF", 0.008),
            base_temp_ref_outside=cfg_mgr.get("PID", "BASE_TEMP_REF_OUTSIDE", 10.0),
            base_temp_boiler=cfg_mgr.get("PID", "BASE_TEMP_BOILER", 45.0),
            valve_input_min=cfg_mgr.get("PID", "VALVE_MIN", 8.0),
            valve_input_max=cfg_mgr.get("PID", "VALVE_MAX", 70.0),
            time_factor=1.0 # Use real-time for actual operation
        )
        logger.info("PID Controller instantiated.")

        # Pass pid_instance to setup_gui
        setup_gui(gui, cfg_mgr, wifi, homematic, opentherm, pid_instance)

    except Exception as e: # Catch init errors
        logger.fatal("Initialization", str(e),resetmachine=not DEVELOPMENT_MODE)
        # Ensure pid_instance remains None if initialization failed before it


    # Start Async Event Loop and Schedule Tasks
    loop = asyncio.get_event_loop()
    # Pass pid_instance and interval to schedule_tasks if pid was created
    # Ensure cfg_mgr exists before accessing it
    if pid_instance and cfg_mgr:
        # Use cfg_mgr.get directly for interval - hoping Any hint suffices
        interval_val = cfg_mgr.get("PID", "UPDATE_INTERVAL_SEC", 30)
        # schedule_tasks expects int, but let's see if linter allows Any
        schedule_tasks(loop, wifi=wifi, hm=homematic, led=led, ot_manager=opentherm, hid=buttons, pid=pid_instance, interval_s=interval_val, cfg_mgr=cfg_mgr)
    else:
        # Schedule without PID if it failed to initialize or cfg_mgr is missing
        logger.error("PID instance or ConfigManager not available, scheduling tasks without PID control.")
        # Schedule tasks without PID related parameters
        schedule_tasks(loop, wifi=wifi, hm=homematic, led=led, ot_manager=opentherm, hid=buttons)

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
