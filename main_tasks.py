import uasyncio as asyncio
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

# --- Start Refactored PID Control Helper Functions ---

async def _sync_ot_takeover(cfg_mgr, ot_manager):
    """Ensures OTGW controller takeover state matches configuration."""
    desired_takeover = cfg_mgr.get("OT", "ENABLE_CONTROLLER", False)
    actual_takeover = ot_manager.is_active()

    if desired_takeover and not actual_takeover:
        logger.info("SYNC: Takeover ON desired, not active. Taking control.")
        ot_manager.take_control()
    elif not desired_takeover and actual_takeover:
        logger.info("SYNC: Takeover OFF desired, but active. Relinquishing control.")
        ot_manager.relinquish_control()


async def _sync_dhw_control(cfg_mgr, ot_manager):
    """Synchronizes DHW enable state and setpoint based on configuration."""
    # Always manage DHW enable/disable based on its specific config toggle
    dhw_enabled = cfg_mgr.get("OT", "ENABLE_DHW", True)
    actual_dhw_state = ot_manager.is_dhw_enabled() # Assumes manager tracks this
    if dhw_enabled != actual_dhw_state:
        logger.info(f"SYNC: Setting DHW enable from {actual_dhw_state} to {dhw_enabled}")
        ot_manager.set_hot_water_mode(1 if dhw_enabled else 0)
    
    # Sync DHW setpoint ONLY if DHW is enabled AND the enforce flag is set
    if dhw_enabled and cfg_mgr.get("OT", "ENFORCE_DHW_SETPOINT", False):
        desired_dhw_sp = cfg_mgr.get("OT", "DHW_SETPOINT", 50.0)
        actual_dhw_sp = ot_manager.get_dhw_setpoint() # Assumes getter exists
        # Compare floats carefully, or just send if different enough?
        if abs(desired_dhw_sp - (actual_dhw_sp if actual_dhw_sp is not None else -999)) > 0.1:
            logger.info(f"SYNC (Enforced): Setting DHW Setpoint from {actual_dhw_sp} to {desired_dhw_sp}")
            ot_manager.set_dhw_setpoint(desired_dhw_sp)


async def _sync_pid_limits(cfg_mgr, pid):
    """Updates the PID controller's output limits based on configuration."""
    # We still need to update the PID limit if the config value changes, 
    # but we won't send the SH command repeatedly here.
    # The SH command is typically set once or when changed via GUI/other means.
    desired_max_ch_sp = cfg_mgr.get("OT", "MAX_HEATING_SETPOINT", 72.0)
    # TODO: Add handling for pid.output_min if it becomes configurable
    if pid: # Check if PID instance exists
        # Use getter/setter if available, otherwise direct access
        current_max = getattr(pid, 'get_output_max', lambda: pid.output_max)()
        if abs(current_max - desired_max_ch_sp) > 0.1:
            logger.info(f"SYNC: Updating PID output_max to {desired_max_ch_sp} (from {current_max:.1f})")
            setter = getattr(pid, 'set_output_max', None)
            if setter:
                setter(desired_max_ch_sp)
            else:
                pid.output_max = desired_max_ch_sp

# --- Start Heating Mode Helpers (Called by _handle_heating_control) ---

async def _handle_auto_heating(cfg_mgr, pid, hm, ot_manager):
    """Determines target state and setpoint for Automatic Heating/PID mode."""
    logger.debug("MODE: Automatic Heating/PID")
    
    target_heating_state = False # Default state is OFF
    target_setpoint = 10.0    # Default CS=10 when heating is OFF

    # --- Auto Heating Logic --- #
    current_ch_state = ot_manager.is_ch_enabled() 
    heating_should_be_enabled = current_ch_state # Assume current state unless changed

    current_temp = hm.temperature
    avg_valve = hm.avg_valve
    # Use cfg_mgr.get directly for float values
    off_temp = cfg_mgr.get("AUTOH", "OFF_TEMP", 20.0) 
    off_valve = cfg_mgr.get("AUTOH", "OFF_VALVE_LEVEL", 6.0)
    on_temp = cfg_mgr.get("AUTOH", "ON_TEMP", 17.0)
    on_valve = cfg_mgr.get("AUTOH", "ON_VALVE_LEVEL", 8.0)

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
        # Add check for enabling heating based only on valve level if temp unavailable? Optional.
        elif current_temp is None and avg_valve is not None and avg_valve > on_valve:
             logger.info(f"AutoHeat: Enabling heating based on valve level ({avg_valve:.1f}%) as temp is unavailable.")
             heating_should_be_enabled = True

    target_heating_state = heating_should_be_enabled

    # If heating should be ON, calculate PID setpoint
    if target_heating_state:
        # Ensure PID instance exists before using it
        if pid:
            current_max_valve = hm.max_valve
            # Use getter if available, otherwise direct access
            base_temp_ref = getattr(pid, 'get_base_temp_ref_outside', lambda: pid.base_temp_ref_outside)()
            current_temp_pid = hm.temperature if hm.temperature is not None else base_temp_ref
            current_wind = hm.wind_speed if hm.wind_speed is not None else 0.0
            current_sun = hm.illumination if hm.illumination is not None else 0.0
            
            pid_output = pid.update(
                current_max_valve, current_wind, current_temp_pid, current_sun
            )
            target_setpoint = pid_output # Use PID output
            logger.info(f"PID Update: MaxValve={current_max_valve:.1f}, Temp={current_temp_pid:.1f}, Wind={current_wind:.1f}, Sun={current_sun:.0f} -> BoilerTemp={target_setpoint:.2f}")
        else:
            logger.error("AutoHeat: PID instance is None, cannot calculate setpoint. Using default.")
            # Fallback: Use manual setpoint or a safe default if PID is missing?
            target_setpoint = cfg_mgr.get("OT", "MANUAL_HEATING_SETPOINT", 55.0)
            logger.warning(f"Falling back to manual/default setpoint: {target_setpoint}")

    else: # AutoHeat determined heating should be OFF
        logger.debug("AutoHeat: Heating OFF. Target CS=10.0")
        # target_setpoint remains 10.0
        
    return target_heating_state, target_setpoint


async def _handle_manual_heating(cfg_mgr):
    """Determines target state and setpoint for Manual Heating mode."""
    logger.debug("MODE: Manual Heating Control")
    
    target_heating_state = False # Default state is OFF
    target_setpoint = 10.0    # Default CS=10 when heating is OFF

    # Use cfg_mgr.get directly for boolean
    manual_heating_desired = cfg_mgr.get("OT", "ENABLE_HEATING", False)
    target_heating_state = manual_heating_desired
    
    if target_heating_state:
        # Use cfg_mgr.get directly for float
        manual_setpoint = cfg_mgr.get("OT", "MANUAL_HEATING_SETPOINT", 55.0)
        target_setpoint = manual_setpoint # Use Manual setpoint
        logger.info(f"ManualHeat: Heating ON. Target CS={target_setpoint:.2f}")
    else:
        logger.debug("ManualHeat: Heating OFF. Target CS=10.0")
        # target_setpoint remains 10.0
        
    return target_heating_state, target_setpoint

# --- End Heating Mode Helpers ---


async def _handle_heating_control(cfg_mgr, pid, hm, ot_manager):
    """Handles the main heating logic (Auto/Manual) when OT controller is active."""
    # Determine mode
    auto_heat_enabled = cfg_mgr.get("AUTOH", "ENABLE", True)
    
    # Get target state and setpoint based on mode
    if auto_heat_enabled:
        target_heating_state, target_setpoint = await _handle_auto_heating(cfg_mgr, pid, hm, ot_manager)
    else:
        target_heating_state, target_setpoint = await _handle_manual_heating(cfg_mgr)

    # === Apply Determined Heating State ===
    actual_heating_state = ot_manager.is_ch_enabled()
    if target_heating_state != actual_heating_state:
        logger.info(f"State Change: Setting CH from {actual_heating_state} to {target_heating_state}")
        ot_manager.set_central_heating(target_heating_state)
    
    # === Apply Determined Control Setpoint ===
    # Only apply heating setpoint if CH is actually ON (or intended to be ON)
    if target_heating_state:
        actual_control_setpoint = ot_manager.get_control_setpoint()
        # Compare floats carefully, or just send if different enough?
        if abs(target_setpoint - (actual_control_setpoint if actual_control_setpoint is not None else -999)) > 0.1:
            logger.info(f"Applying Control Setpoint: {target_setpoint:.2f} (Previous: {actual_control_setpoint})")
            ot_manager.set_control_setpoint(target_setpoint)
        else:
            logger.debug(f"Control Setpoint unchanged: {target_setpoint:.2f}")
    else: # Heating is OFF, ensure control setpoint is low (e.g., 10)
        actual_control_setpoint = ot_manager.get_control_setpoint()
        if actual_control_setpoint is None or abs(actual_control_setpoint - 10.0) > 0.1:
            logger.info(f"Heating OFF, ensuring Control Setpoint is 10.0 (was {actual_control_setpoint})")
            ot_manager.set_control_setpoint(10.0) # Ensure low setpoint when CH off

# --- End Refactored PID Control Helper Functions ---


async def pid_control_task(pid, hm, ot_manager, interval_s, cfg_mgr):
    """Periodically syncs OT state and applies PID or manual control based on config."""
    logger.info(f"Starting PID/Manual Control task with interval {interval_s}s.")
    await asyncio.sleep(5) # Initial delay

    while True:
        try:
            # Sync basic states regardless of takeover
            await _sync_ot_takeover(cfg_mgr, ot_manager)
            await _sync_dhw_control(cfg_mgr, ot_manager)
            await _sync_pid_limits(cfg_mgr, pid) # Sync PID limits even if controller isn't active

            # Perform heating control only if OT manager has control
            if ot_manager.is_active():
                await _handle_heating_control(cfg_mgr, pid, hm, ot_manager)
            else:
                # Combined debug log for takeover OFF
                logger.debug("Takeover OFF: Skipping heating control actions.")

            # Use actual sleep interval (already retrieved as int in main.py)
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