import uasyncio as asyncio
# from managers.manager_logger import Logger # No longer needed directly

# Import the logger instance initialized in initialization.py
from managers.manager_logger import Logger

logger = Logger()

# Helper function to safely convert config values to boolean
def _config_str_to_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() == "true"

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


async def pid_control_task(pid, hm, ot_manager, interval_s, cfg_mgr):
    """Periodically syncs OT state and applies PID or manual control based on config."""
    logger.info(f"Starting PID/Manual Control task with interval {interval_s}s.")
    await asyncio.sleep(5)

    while True:
        try:
            # --- Synchronize OT Control State (Takeover) --- #
            desired_takeover = _config_str_to_bool(cfg_mgr.get_value("OT", "ENABLE_CONTROLLER"), default=False)
            actual_takeover = ot_manager.is_active()

            if desired_takeover and not actual_takeover:
                logger.info("SYNC: Takeover ON desired, not active. Taking control.")
                ot_manager.take_control()
            elif not desired_takeover and actual_takeover:
                logger.info("SYNC: Takeover OFF desired, but active. Relinquishing control.")
                ot_manager.relinquish_control()
            # --- End OT Control State Sync --- #

            # --- Main Control Logic (Only if Takeover is Active) --- #
            if ot_manager.is_active():
                auto_heat_enabled = _config_str_to_bool(cfg_mgr.get_value("AUTOH", "ENABLE"), default=False)
                
                target_heating_state = False # Final desired state for CH=1/0 for this cycle
                target_setpoint = 10.0    # Default CS=10 when heating is OFF

                # === Determine Target State and Setpoint ===
                if auto_heat_enabled:
                    logger.debug("MODE: Automatic Heating/PID")
                    # --- Auto Heating Logic --- #
                    current_ch_state = ot_manager.is_ch_enabled() 
                    heating_should_be_enabled = current_ch_state # Assume current state unless changed

                    current_temp = hm.temperature
                    avg_valve = hm.avg_valve
                    off_temp = float(cfg_mgr.get_value("AUTOH", "OFF_TEMP", 20.0)) 
                    off_valve = float(cfg_mgr.get_value("AUTOH", "OFF_VALVE_LEVEL", 6.0))
                    on_temp = float(cfg_mgr.get_value("AUTOH", "ON_TEMP", 17.0))
                    on_valve = float(cfg_mgr.get_value("AUTOH", "ON_VALVE_LEVEL", 8.0))

                    if current_ch_state: # Currently ON? Check OFF conditions
                        if current_temp is not None and current_temp >= off_temp:
                            logger.info(f"AutoHeat: Condition met to disable heating (Temp {current_temp:.1f}C >= {off_temp:.1f}C)")
                            heating_should_be_enabled = False
                        elif avg_valve is not None and avg_valve < off_valve:
                            logger.info(f"AutoHeat: Condition met to disable heating (Avg Valve {avg_valve:.1f}% < {off_valve:.1f}%)")
                            heating_should_be_enabled = False
                    else: # Currently OFF? Check ON conditions
                        if (current_temp is not None and avg_valve is not None and
                            current_temp < on_temp and avg_valve > on_valve):
                            logger.info(f"AutoHeat: Condition met to enable heating (Temp {current_temp:.1f}C < {on_temp:.1f}C AND Avg Valve {avg_valve:.1f}% > {on_valve:.1f}%)")
                            heating_should_be_enabled = True
                    
                    target_heating_state = heating_should_be_enabled

                    # If heating should be ON, calculate PID setpoint
                    if target_heating_state:
                        current_max_valve = hm.max_valve
                        current_temp_pid = hm.temperature if hm.temperature is not None else pid.base_temp_ref_outside
                        current_wind = hm.wind_speed if hm.wind_speed is not None else 0.0
                        current_sun = hm.illumination if hm.illumination is not None else 0.0
                        
                        pid_output = pid.update(
                            current_max_valve, current_wind, current_temp_pid, current_sun
                        )
                        target_setpoint = pid_output # Use PID output
                        logger.info(f"PID Update: MaxValve={current_max_valve:.1f}, Temp={current_temp_pid:.1f}, Wind={current_wind:.1f}, Sun={current_sun:.0f} -> BoilerTemp={target_setpoint:.2f}")
                    else:
                        logger.debug("AutoHeat: Heating OFF. Target CS=10.0")
                        # target_setpoint remains 10.0

                # === MANUAL MODE ===
                else: 
                    logger.debug("MODE: Manual Heating Control")
                    manual_heating_desired = _config_str_to_bool(cfg_mgr.get_value("OT", "ENABLE_HEATING"), default=False)
                    target_heating_state = manual_heating_desired
                    
                    if target_heating_state:
                        manual_setpoint = float(cfg_mgr.get_value("OT", "MANUAL_HEATING_SETPOINT", 55.0))
                        target_setpoint = manual_setpoint # Use Manual setpoint
                        logger.info(f"ManualHeat: Heating ON. Target CS={target_setpoint:.2f}")
                    else:
                        logger.debug("ManualHeat: Heating OFF. Target CS=10.0")
                        # target_setpoint remains 10.0

                # === Apply Determined State ===
                actual_heating_state = ot_manager.is_ch_enabled()
                if target_heating_state != actual_heating_state:
                    logger.info(f"State Change: Setting CH from {actual_heating_state} to {target_heating_state}")
                    ot_manager.set_central_heating(target_heating_state)
                
                # Always apply the target setpoint (either PID, Manual, or 10.0)
                logger.info(f"Applying Control Setpoint: {target_setpoint:.2f}")
                ot_manager.set_control_setpoint(target_setpoint)
            
            # --- End Main Control Logic --- #
            else: # Takeover is OFF
                 logger.debug("Takeover OFF: Skipping all heating control actions.")

            # Use actual sleep interval from config
            await asyncio.sleep(interval_s)

        except Exception as e:
            logger.error(f"PID/Control Task Error: {e}")
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