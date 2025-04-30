import uasyncio as asyncio
import gc # Added import
# from managers.manager_logger import Logger # No longer needed directly

# Import the logger instance initialized in initialization.py
from managers.manager_logger import Logger

logger = Logger()

# Remove the helper function - no longer needed with JSON types
# def _config_str_to_bool(value, default=False):
#     if value is None:
#         return default
#     return str(value).strip().lower() == "true"

async def wifi_task(wifi):
    while True:
        try:
            wifi.update()
        except Exception as e:  # noqa: BLE001
            logger.error(f"WiFi: {e}")
        await asyncio.sleep(5)


async def led_task(led):
    while True:
        try:
            led.update()
        except Exception as e:  # noqa: BLE001
            logger.error(f"LED: {e}")
        await asyncio.sleep_ms(100)


async def homematic_task(hm, wdt):
    while True:
        try:
            gc.collect() # Collect garbage
            hm.update()
            wdt.feed() # Feed watchdog
        except Exception as e:  # noqa: BLE001
            logger.error(f"HM: {e}")
        await asyncio.sleep(5)


async def poll_buttons_task(hid):
    while True:
        hid.get_event()
        await asyncio.sleep_ms(20)


async def error_rate_limiter_task(hm, wifi, led):
    """Watch the logger's limiter flag and perform a quick reset cycle."""
    while True:
        if logger.error_rate_limiter_reached:
            logger.warning("Error‑rate limiter TRIGGERED – running cooldown cycle")
            try:
                hm.set_paused(True)
                wifi.disconnect()
                led.set_color("red", blink=False)
            except Exception as e:  # noqa: BLE001
                logger.error(f"Limiter prep: {e}")

            logger.reset_error_rate_limiter()

            try:
                hm.set_paused(False)
                wifi.update()
            except Exception as e:  # noqa: BLE001
                logger.error(f"Limiter resume: {e}")
        await asyncio.sleep(1)


async def main_status_task(hm, wifi, led):
    while True:
        if wifi.is_connected():
            hm.set_paused(False)
            led.set_color("green" if hm.is_ccu_connected() else "magenta",
                           blink=True, duration_on=50, duration_off=2000)
        else:
            hm.set_paused(True)
            led.set_color("red", blink=True, duration_on=1000, duration_off=1000)

        await asyncio.sleep(1)

async def pid_control_task(pid, hm, ot_manager, cfg_mgr, heating_controller):
    """Periodically runs the heating controller's update method."""
    logger.info("Starting PID/Manual Control task")
    await asyncio.sleep(5)  # Initial delay

    while True:
        try:
            await heating_controller.update()
            await asyncio.sleep(30)  # Use configurable interval if needed
        except Exception as e:
            logger.error(f"PID/Control Task Error: {e}")
            await asyncio.sleep(30)  # Avoid rapid looping on error

async def log_pid_output_task(pid):
    """Periodically logs the last calculated PID output temperature."""
    logger.info(f"Starting PID output logging task.")
    # Initial delay aligns potentially with first PID calculation
    await asyncio.sleep(60)

    while True:
        try:
            last_output = pid.last_output
            if last_output is not None:
                logger.info(f"PID Last Output: {last_output:.2f}")
            else:
                logger.info("PID Last Output: None (PID not run yet?)")
            
            await asyncio.sleep(60)

        except Exception as e:
            logger.error(f"PID Log Task Error: {e}")
            # Avoid rapid looping on error
            await asyncio.sleep(60)

async def log_memory_task():
    """Periodically logs the free memory."""
    logger.info("Starting Free Memory logging task.")
    await asyncio.sleep(5) # Small initial delay

    while True:
        try:
            free_memory = gc.mem_free()
            logger.info(f"Free Memory: {free_memory} bytes")
            gc.collect() # Optional: Run garbage collection after logging
            await asyncio.sleep(60)

        except Exception as e:
            logger.error(f"Memory Log Task Error: {e}")
            # Avoid rapid looping on error
            await asyncio.sleep(60)

async def message_server_task(server):
    """Runs the message server's main loop."""
    if server:
        await server.run() # The run method now contains its own loop
    else:
        logger.warning("Message Server task started, but server instance is None.")
        # Keep task alive but do nothing if server isn't there
        while True:
            await asyncio.sleep(3600) # Sleep for a long time 

async def heating_controller_task(heating_controller):
    """Periodically runs the heating controller's update method."""
    logger.info("Starting Heating Controller task")
    await asyncio.sleep(5)  # Initial delay

    while True:
        try:
            await heating_controller.update()
            await asyncio.sleep(30)  # Use configurable interval if needed
        except Exception as e:
            logger.error(f"Heating Controller Task Error: {e}")
            await asyncio.sleep(30)  # Avoid rapid looping on error 