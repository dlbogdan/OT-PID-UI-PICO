"""
main.py


"""

# --------------------------------------------------------------------------- #
#  Imports
# --------------------------------------------------------------------------- #
import utime as time
import uasyncio as asyncio
import uos
from machine import WDT
# Import initialization functions
from managers.manager_logger import Logger
from flags import DEBUG
logger = Logger(DEBUG)

from initialization import initialize_hardware, initialize_services, setup_gui
# 3rd‑party / project modules

from managers.gui import GUIManager
from managers.manager_config import ConfigManager
from platform_spec import ConfigFileName

# Import tasks from the new file
from main_tasks import (
    wifi_task, led_task, homematic_task, poll_buttons_task,
    error_rate_limiter_task, main_status_task,
    log_pid_output_task, log_memory_task, message_server_task, heating_controller_task # Import the new tasks
)

DEVELOPMENT_MODE=1

# --------------------------------------------------------------------------- #
#  Background task registration
# --------------------------------------------------------------------------- #

def schedule_tasks(loop, *, wifi, hm, led, ot_manager, hid, pid, cfg, message_server, wdt, heating_controller):
    # Tasks are now imported from main_tasks.py
    tasks_to_schedule = [
        wifi_task(wifi), 
        led_task(led), 
        homematic_task(hm, wdt),
        poll_buttons_task(hid), 
        main_status_task(hm, wifi, led),
        error_rate_limiter_task(hm, wifi, led),
        heating_controller_task(heating_controller),
        log_pid_output_task(pid),
        log_memory_task(), # Add memory logging task
        message_server_task(message_server), # Add message server task
        ot_manager.start()
    ]
        
    for coro in tasks_to_schedule:
        loop.create_task(coro)


# --------------------------------------------------------------------------- #
#  Main Application Logic
# --------------------------------------------------------------------------- #

async def main():  # noqa: C901 (Complexity will be reduced)
    # Initialize Config First
    try:
        logger.info("Initializing configuration...")
        cfg = ConfigManager(ConfigFileName())
        logger.info("Configuration initialized.")
    except Exception as e:
        logger.fatal("Config initialization failed", str(e), resetmachine=not DEVELOPMENT_MODE)
        return

    # Initialize Hardware with Config
    try:
        display, led, buttons = initialize_hardware(cfg)
        # Initialize remaining services
        wifi, homematic, pid, message_server, heating_controller = initialize_services()[1:]  # Skip cfg return
        gui = GUIManager(display, buttons) 
        setup_gui(gui, cfg, wifi, homematic, heating_controller._ot, pid, heating_controller)

        # Initialize Hardware Watchdog Timer (8 seconds timeout)
        logger.info("Initializing Hardware Watchdog (8s timeout)...")
        wdt = WDT(timeout=8000)
        logger.info("Watchdog Initialized.")

    except Exception as e: # Catch init errors
        logger.fatal("Initialization", str(e), resetmachine=not DEVELOPMENT_MODE)
        return

    # Start Async Event Loop and Schedule Tasks
    loop = asyncio.get_event_loop()
    try:
        # Pass the wdt instance created above
        schedule_tasks(loop, wifi=wifi, hm=homematic, led=led, ot_manager=heating_controller._ot, 
                      hid=buttons, pid=pid, cfg=cfg, message_server=message_server, wdt=wdt,
                      heating_controller=heating_controller)
    except Exception as e:
        logger.fatal("Scheduling tasks", str(e), resetmachine=not DEVELOPMENT_MODE)
        return
        
    # Main Loop
    try:
        logger.info("Starting main event loop...")
        loop.run_forever()
    except KeyboardInterrupt:
        logger.warning("KeyboardInterrupt received, shutting down...")
    except Exception as e:
        logger.fatal("MainLoopError", str(e), resetmachine=not DEVELOPMENT_MODE)
    finally:
        logger.info("Performing shutdown cleanup...")
        display.clear()
        display.show_message("System", "Shutting down...")
        led.direct_send_color("black") # Turn off LED
        logger.info("Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
