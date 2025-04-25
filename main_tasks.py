import uasyncio as asyncio
# from managers.manager_logger import Logger # No longer needed directly

# Import the logger instance initialized in initialization.py
from managers.manager_logger import Logger

logger = Logger()



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


async def homematic_task(hm):
    while True:
        try:
            hm.update()
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


async def pid_control_task(pid, hm, ot_manager, interval_s):
    """Periodically calculates and applies the PID control output."""
    logger.info(f"Starting PID task with interval {interval_s}s.")
    # Small initial delay to allow other systems to stabilize?
    await asyncio.sleep(5)

    while True:
        try:
            # Use actual sleep interval from config
            await asyncio.sleep(interval_s)

            # Check if OT control is active and heating is enabled
            # Note: These checks might need refinement based on exact OT manager logic
            if ot_manager.is_active() and ot_manager.is_ch_enabled():
                
                # Get valve input
                current_max_valve = hm.max_valve
                #todo
                # Get weather data (PLACEHOLDER - Needs real implementation later)
                # You'll need a weather service/sensor readings here
                current_wind = 0.0 # km/h
                current_temp = 10.0 # deg C
                current_sun = 0.0 # lux
                
                # Calculate PID output
                output_temp = pid.update(
                    current_max_valve,
                    current_wind,
                    current_temp,
                    current_sun
                )
                
                logger.info(f"PID Update: MaxValve={current_max_valve:.1f} -> BoilerTemp={output_temp:.2f}")
                
                # Apply the calculated temperature to the OpenTherm controller
                ot_manager.set_control_setpoint(output_temp)

            else:
                # Optional: Log that PID is inactive
                # logger.debug("PID inactive (OT control/heating disabled)")
                pass # Do nothing if controller or heating is disabled

        except Exception as e:
            logger.error(f"PID Task Error: {e}")
            # Avoid rapid looping on error
            await asyncio.sleep(interval_s) 