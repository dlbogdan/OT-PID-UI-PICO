"""
Heating Controller module for OT-PID-UI-PICO.

This module contains the HeatingController class, which encapsulates
the logic for controlling heating based on various modes (auto, manual)
and conditions (temperature, valve openings).
"""

from managers.manager_logger import Logger

logger = Logger()

class HeatingController:
    """
    HeatingController manages central heating decisions based on configured
    mode (auto or manual) and conditions like temperature, valve openings.
    """
    def __init__(self, config_manager, homematic_service, pid_controller, ot_manager):
        """
        Initialize the HeatingController.
        
        Args:
            config_manager: Configuration manager instance
            homematic_service: Homematic data service instance
            pid_controller: PID controller instance
            ot_manager: OpenTherm manager instance
        """
        self._config = config_manager
        self._hm = homematic_service
        self._pid = pid_controller
        self._ot = ot_manager
        
        # State flags
        self._force_on_next_cycle = False
        self._force_off_next_cycle = False
    
    def trigger_heating_on(self):
        """Sets the flag to force heating ON in the next cycle."""
        self._force_on_next_cycle = True
        logger.info("ACTION: Triggered Heating ON for next cycle.")
    
    def trigger_heating_off(self):
        """Sets the flag to force heating OFF in the next cycle."""
        self._force_off_next_cycle = True
        logger.info("ACTION: Triggered Heating OFF for next cycle.")
    
    async def update(self):
        """
        Main update method that handles heating control logic.
        Determines the heating state and setpoint based on mode and conditions.
        Applies the state and setpoint to the OpenTherm manager.
        """
        # Sync basic states regardless of takeover
        # Import the sync functions here to avoid circular imports
        from main_tasks import _sync_ot_takeover, _sync_dhw_control, _sync_pid_limits, _sync_pid_params
        await _sync_ot_takeover(self._config, self._ot)
        await _sync_dhw_control(self._config, self._ot)
        await _sync_pid_limits(self._config, self._pid)
        await _sync_pid_params(self._config, self._pid)

        # Only perform heating control if OT manager has control
        if not self._ot.is_active():
            logger.debug("Takeover OFF: Skipping heating control actions.")
            return
            
        # Determine mode
        auto_heat_enabled = self._config.get("AUTOH", "ENABLE", True)
        
        # Get target state and setpoint based on mode
        if auto_heat_enabled:
            target_heating_state, target_setpoint = self._handle_auto_heating()
        else:
            target_heating_state, target_setpoint = self._handle_manual_heating()

        # Apply the determined heating state
        actual_heating_state = self._ot.is_ch_enabled()
        if target_heating_state != actual_heating_state:
            logger.info(f"State Change: Setting CH from {actual_heating_state} to {target_heating_state}")
            self._ot.set_central_heating(target_heating_state)
        
        # Apply the determined control setpoint
        if target_heating_state:
            actual_control_setpoint = self._ot.get_control_setpoint()
            # Compare floats carefully, or just send if different enough
            if abs(target_setpoint - (actual_control_setpoint if actual_control_setpoint is not None else -999)) > 0.1:
                logger.info(f"Applying Control Setpoint: {target_setpoint:.2f} (Previous: {actual_control_setpoint})")
                self._ot.set_control_setpoint(target_setpoint)
            else:
                logger.debug(f"Control Setpoint unchanged: {target_setpoint:.2f}")
        else:  # Heating is OFF, ensure control setpoint is low (e.g., 10)
            actual_control_setpoint = self._ot.get_control_setpoint()
            if actual_control_setpoint is None or abs(actual_control_setpoint - 10.0) > 0.1:
                logger.info(f"Heating OFF, ensuring Control Setpoint is 10.0 (was {actual_control_setpoint})")
                self._ot.set_control_setpoint(10.0)  # Ensure low setpoint when CH off
    
    def _handle_auto_heating(self):
        """
        Determines target state and setpoint for Automatic Heating/PID mode.
        
        Returns:
            tuple: (target_heating_state, target_setpoint)
        """
        logger.debug("MODE: Automatic Heating/PID")
        
        target_heating_state = False  # Default state is OFF
        target_setpoint = 10.0        # Default CS=10 when heating is OFF
        override_active = False

        # --- Check for manual overrides --- #
        if self._force_on_next_cycle:
            logger.info("AutoHeat OVERRIDE: Forcing heating ON this cycle.")
            target_heating_state = True
            self._force_on_next_cycle = False  # Consume the flag
            override_active = True
        elif self._force_off_next_cycle:
            logger.info("AutoHeat OVERRIDE: Forcing heating OFF this cycle.")
            target_heating_state = False
            self._force_off_next_cycle = False  # Consume the flag
            override_active = True

        # --- Auto Heating Logic --- #
        current_ch_state = self._ot.is_ch_enabled() 

        # Run normal logic ONLY if no override was active
        if not override_active:
            heating_should_be_enabled = current_ch_state  # Assume current state unless changed

            current_temp = self._hm.temperature
            avg_level = self._hm.avg_active_valve
            # Use _config.get directly for float values
            off_temp = self._config.get("AUTOH", "OFF_TEMP", 19.0) 
            off_valve = self._config.get("AUTOH", "OFF_VALVE_LEVEL", 5.0)
            on_temp = self._config.get("AUTOH", "ON_TEMP", 15.0)
            on_valve = self._config.get("AUTOH", "ON_VALVE_LEVEL", 12.0)

            if current_ch_state:  # Currently ON? Check OFF conditions
                if current_temp is not None and current_temp >= off_temp:
                    logger.info(f"AutoHeat: Condition met to disable heating (Temp {current_temp:.1f}C >= {off_temp:.1f}C)")
                    heating_should_be_enabled = False
                elif avg_level is not None and avg_level < off_valve:
                    logger.info(f"AutoHeat: Condition met to disable heating (Avg Valve {avg_level:.1f}% < {off_valve:.1f}%)")
                    heating_should_be_enabled = False
            else:  # Currently OFF? Check ON conditions
                if (current_temp is not None and avg_level is not None and
                    current_temp < on_temp and avg_level > on_valve):
                    logger.info(f"AutoHeat: Condition met to enable heating (Temp {current_temp:.1f}C < {on_temp:.1f}C AND Avg Valve {avg_level:.1f}% > {on_valve:.1f}%)")
                    heating_should_be_enabled = True
                # Add check for enabling heating based only on valve level if temp unavailable
                elif current_temp is None and avg_level is not None and avg_level > on_valve:
                    logger.info(f"AutoHeat: Enabling heating based on valve level ({avg_level:.1f}%) as temp is unavailable.")
                    heating_should_be_enabled = True

            target_heating_state = heating_should_be_enabled

        # If heating should be ON, calculate PID setpoint
        if target_heating_state:
            # Ensure PID instance exists before using it
            if self._pid:
                current_level = self._hm.avg_active_valve
                # Use getter if available, otherwise direct access
                base_temp_ref = getattr(self._pid, 'get_base_temp_ref_outside', lambda: self._pid.base_temp_ref_outside)()
                current_temp_pid = self._hm.temperature if self._hm.temperature is not None else base_temp_ref
                current_wind = self._hm.wind_speed if self._hm.wind_speed is not None else 0.0
                current_sun = self._hm.illumination if self._hm.illumination is not None else 0.0
                
                pid_output = self._pid.update(
                    current_level, current_wind, current_temp_pid, current_sun
                )
                target_setpoint = pid_output  # Use PID output
                logger.info(f"PID Update: current_level(valve)={current_level:.1f}, Temp={current_temp_pid:.1f}, Wind={current_wind:.1f}, Sun={current_sun:.0f} -> BoilerTemp={target_setpoint:.2f}")
            else:
                logger.error("AutoHeat: PID instance is None, cannot calculate setpoint. Using default.")
                # Fallback: Use manual setpoint or a safe default if PID is missing
                target_setpoint = self._config.get("OT", "MANUAL_HEATING_SETPOINT", 55.0)
                logger.warning(f"Falling back to manual/default setpoint: {target_setpoint}")
        else:  # AutoHeat determined heating should be OFF
            logger.debug("AutoHeat: Heating OFF. Target CS=10.0")
            # target_setpoint remains 10.0
            
        return target_heating_state, target_setpoint

    def _handle_manual_heating(self):
        """
        Determines target state and setpoint for Manual Heating mode.
        
        Returns:
            tuple: (target_heating_state, target_setpoint)
        """
        logger.debug("MODE: Manual Heating Control")
        
        target_heating_state = False  # Default state is OFF
        target_setpoint = 10.0        # Default CS=10 when heating is OFF

        # Use _config.get directly for boolean
        manual_heating_desired = self._config.get("OT", "ENABLE_HEATING", False)
        target_heating_state = manual_heating_desired
        
        if target_heating_state:
            # Use _config.get directly for float
            manual_setpoint = self._config.get("OT", "MANUAL_HEATING_SETPOINT", 55.0)
            target_setpoint = manual_setpoint  # Use Manual setpoint
            logger.info(f"ManualHeat: Heating ON. Target CS={target_setpoint:.2f}")
        else:
            logger.debug("ManualHeat: Heating OFF. Target CS=10.0")
            # target_setpoint remains 10.0
            
        return target_heating_state, target_setpoint 