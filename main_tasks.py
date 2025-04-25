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


async def pid_control_task(pid, hm, ot_manager, interval_s, cfg):
    """Periodically calculates and applies the PID control output, with auto heating control."""
    logger.info(f"Starting PID task with interval {interval_s}s.")
    # Small initial delay to allow other systems to stabilize?
    await asyncio.sleep(5)

    while True:
        try:
            # --- Determine Intended Heating State --- # 
            # Start with the current actual state
            heating_should_be_enabled = ot_manager.is_ch_enabled()
            original_heating_state = heating_should_be_enabled 

            auto_heat_enabled = cfg.get("auto_heat_enable", False)
            
            if auto_heat_enabled:
                current_temp = hm.temperature
                avg_valve = hm.avg_valve

                disable_temp = cfg.get("auto_heat_disable_temp", 20.0)
                disable_valve = cfg.get("auto_heat_disable_valve", 6.0)
                enable_temp = cfg.get("auto_heat_enable_temp", 17.0)
                enable_valve = cfg.get("auto_heat_enable_valve", 8.0)

                # Check Disable Conditions first (if currently enabled)
                if heating_should_be_enabled:
                    if current_temp is not None and current_temp >= disable_temp:
                        logger.info(f"AutoHeat: Condition met to disable heating (Temp {current_temp:.1f}C >= {disable_temp:.1f}C)")
                        heating_should_be_enabled = False
                    elif avg_valve is not None and avg_valve < disable_valve:
                        logger.info(f"AutoHeat: Condition met to disable heating (Avg Valve {avg_valve:.1f}% < {disable_valve:.1f}%)")
                        heating_should_be_enabled = False
                
                # Check Enable Condition (if currently disabled according to our logic)
                # Prevents flapping if disable condition is met right after enabling
                if not heating_should_be_enabled: 
                    if (current_temp is not None and avg_valve is not None and
                        current_temp < enable_temp and avg_valve > enable_valve):
                        # Check if we were originally off or auto-disabled just now
                        # This avoids enabling if heating was manually turned off?
                        # For now, let's assume auto-control overrides manual if conditions met.
                        logger.info(f"AutoHeat: Condition met to enable heating (Temp {current_temp:.1f}C < {enable_temp:.1f}C AND Avg Valve {avg_valve:.1f}% > {enable_valve:.1f}%)")
                        heating_should_be_enabled = True
            
            # --- Apply Heating State Change (if needed) --- #
            # Compare intended state with the original state read at the start
            if heating_should_be_enabled != original_heating_state:
                logger.info(f"AutoHeat: Changing heating state from {original_heating_state} to {heating_should_be_enabled}")
                ot_manager.set_central_heating(heating_should_be_enabled)
            # --- End Automatic Heating Control --- #

            # Log the manager status (reflects state *before* any command sent above might complete)
            logger.debug(f"PID Check: is_active={ot_manager.is_active()}, intended_heating={heating_should_be_enabled}")

            # --- PID Calculation and Setpoint Application --- #
            # Check if OT control is active AND heating should be enabled for this cycle
            if ot_manager.is_active() and heating_should_be_enabled:
                
                # Get valve input
                current_max_valve = hm.max_valve
                
                # Get real weather data (read temp again for PID, potentially slightly different)
                current_temp_pid = hm.temperature if hm.temperature is not None else pid.base_temp_ref_outside
                current_wind = hm.wind_speed if hm.wind_speed is not None else 0.0
                current_sun = hm.illumination if hm.illumination is not None else 0.0
                
                # Calculate PID output
                output_temp = pid.update(
                    current_max_valve,
                    current_wind,
                    current_temp_pid, # Use potentially updated temp
                    current_sun
                )
                
                # Apply the calculated temperature (Heating state confirmed above)
                logger.info(f"PID Update: MaxValve={current_max_valve:.1f}, Temp={current_temp_pid:.1f}, Wind={current_wind:.1f}, Sun={current_sun:.0f} -> BoilerTemp={output_temp:.2f}")
                ot_manager.set_control_setpoint(output_temp)

            elif ot_manager.is_active() and not heating_should_be_enabled:
                # Log that PID is skipped because heating is intended to be off
                logger.debug(f"PID skipped: Heating is disabled for this cycle (intended_state={heating_should_be_enabled}).")
            else: # Not active
                logger.debug(f"PID skipped: Controller not active (is_active={ot_manager.is_active()}).")
            

            # Use actual sleep interval from config
            await asyncio.sleep(interval_s)

        except Exception as e:
            logger.error(f"PID Task Error: {e}")
            # Avoid rapid looping on error
            await asyncio.sleep(interval_s)


async def log_pid_output_task(pid, interval_s=60):
    """Periodically logs the last calculated PID output temperature."""
    logger.info(f"Starting PID output logging task with interval {interval_s}s.")
    # Initial delay aligns potentially with first PID calculation
    await asyncio.sleep(interval_s)

    while True:
        try:
            last_output = pid.last_output
            if last_output is not None:
                logger.info(f"PID Last Output: {last_output:.2f}")
            else:
                logger.info("PID Last Output: None (PID not run yet?)")
            
            await asyncio.sleep(interval_s)

        except Exception as e:
            logger.error(f"PID Log Task Error: {e}")
            # Avoid rapid looping on error
            await asyncio.sleep(interval_s) 