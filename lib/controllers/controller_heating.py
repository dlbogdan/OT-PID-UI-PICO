"""
Heating Controller module for OT-PID-UI-PICO.

This module contains the HeatingController class, which encapsulates
the logic for controlling heating based on various modes (auto, manual)
and conditions (temperature, valve openings).
"""

from managers.manager_logger import Logger
from controllers.controller_feedforward import FeedforwardController

logger = Logger()

class HeatingController:
    """
    HeatingController manages central heating decisions based on configured
    mode (auto or manual) and conditions like temperature, valve openings.
    """
    def __init__(self, config_manager, homematic_service, ot_manager, pid_controller, feedforward_controller):
        """
        Initialize the HeatingController.
        
        Args:
            config_manager: Configuration manager instance
            homematic_service: Homematic data service instance
            ot_manager: OpenTherm manager instance
            pid_controller: PID controller instance
            feedforward_controller: Feedforward controller instance for weather compensation
        """
        self._config = config_manager
        self._hm = homematic_service
        self._pid = pid_controller
        self._ot = ot_manager
        self._feedforward = feedforward_controller
        
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

    async def _sync_ot_takeover(self):
        """Ensures OTGW controller takeover state matches configuration."""
        desired_takeover = self._config.get("OT", "ENABLE_CONTROLLER")
        actual_takeover = self._ot.is_active()

        if desired_takeover and not actual_takeover:
            logger.info("SYNC: Takeover ON desired, not active. Taking control.")
            self._ot.take_control()
        elif not desired_takeover and actual_takeover:
            logger.info("SYNC: Takeover OFF desired, but active. Relinquishing control.")
            self._ot.relinquish_control()

    async def _sync_dhw_control(self):
        """Synchronizes DHW enable state and setpoint based on configuration."""
        # Always manage DHW enable/disable based on its specific config toggle
        dhw_enabled = self._config.get("OT", "ENABLE_DHW")
        actual_dhw_state = self._ot.is_dhw_enabled()
        if dhw_enabled != actual_dhw_state:
            logger.info(f"SYNC: Setting DHW enable from {actual_dhw_state} to {dhw_enabled}")
            self._ot.set_hot_water_mode(1 if dhw_enabled else 0)
        
        # Sync DHW setpoint ONLY if DHW is enabled AND the enforce flag is set
        if dhw_enabled and self._config.get("OT", "ENFORCE_DHW_SETPOINT"):
            desired_dhw_sp = self._config.get("OT", "DHW_SETPOINT")
            actual_dhw_sp = self._ot.get_dhw_setpoint()
            tolerance = self._config.get("OT", "SETPOINT_TOLERANCE")
            if abs(desired_dhw_sp - actual_dhw_sp) > tolerance:
                logger.info(f"SYNC (Enforced): Setting DHW Setpoint from {actual_dhw_sp} to {desired_dhw_sp}")
                self._ot.set_dhw_setpoint(desired_dhw_sp)

    async def _sync_pid_limits(self):
        """Updates the PID controller's output limits based on configuration."""
        if not self._pid:
            return

        desired_max_ch_sp = self._config.get("OT", "MAX_HEATING_SETPOINT")
        self._pid.set_output_max(desired_max_ch_sp)

        cfg_output_min = self._config.get("PID", "MIN_HEATING_SETPOINT")
        self._pid.set_output_min(cfg_output_min)

    async def _sync_pid_params(self):
        """Synchronizes PID parameters from config to the PID instance."""
        if not self._pid:
            return

        self._pid.set_kp(self._config.get("PID", "KP"))
        self._pid.set_ki(self._config.get("PID", "KI"))
        self._pid.set_kd(self._config.get("PID", "KD"))
        self._pid.set_setpoint(self._config.get("PID", "SETPOINT"))
        self._pid.set_valve_input_min(self._config.get("PID", "VALVE_MIN"))
        self._pid.set_valve_input_max(self._config.get("PID", "VALVE_MAX"))
        self._pid.set_output_deadband(self._config.get("PID", "OUTPUT_DEADBAND"))
        self._pid.set_integral_accumulation_range(self._config.get("PID", "INTEGRAL_ACCUMULATION_RANGE"))

    async def _sync_feedforward_params(self):
        """Synchronizes feedforward parameters from config."""
        self._feedforward.set_wind_coeff(self._config.get("FEEDFORWARD", "WIND_COEFF"))
        self._feedforward.set_temp_coeff(self._config.get("FEEDFORWARD", "TEMP_COEFF"))
        self._feedforward.set_sun_coeff(self._config.get("FEEDFORWARD", "SUN_COEFF"))
        self._feedforward.set_wind_chill_coeff(self._config.get("FEEDFORWARD", "WIND_CHILL_COEFF"))
        self._feedforward.set_base_temp_ref_outside(self._config.get("FEEDFORWARD", "BASE_TEMP_REF_OUTSIDE"))
        self._feedforward.set_base_temp_boiler(self._config.get("FEEDFORWARD", "BASE_TEMP_BOILER"))
    
    async def update(self):
        """
        Main update method that handles heating control logic.
        Determines the heating state and setpoint based on mode and conditions.
        Applies the state and setpoint to the OpenTherm manager.
        """
        # Sync basic states regardless of takeover
        await self._sync_ot_takeover()
        await self._sync_dhw_control()
        await self._sync_pid_limits()
        await self._sync_pid_params()
        await self._sync_feedforward_params()

        # Only perform heating control if OT manager has control
        if not self._ot.is_active():
            logger.debug("Takeover OFF: Skipping heating control actions.")
            return
            
        # Determine mode
        auto_heat_enabled = self._config.get("AUTOH", "ENABLE")
        
        # Get target state and setpoint based on mode
        if auto_heat_enabled:
            target_heating_state, target_setpoint = self._handle_auto_heating()
        else:
            target_heating_state, target_setpoint = self._handle_manual_heating()

        # Apply the determined heating state
        actual_heating_state = self._ot.is_ch_enabled()
        if target_heating_state != actual_heating_state:
            logger.info(f"State Change: Setting CH from {actual_heating_state} to {target_heating_state}")
            # Reset PID state on any heating state transition
            if self._pid:
                logger.info("Heating state changing: Resetting PID state")
                self._pid.reset()
            self._ot.set_central_heating(target_heating_state)
        
        # Apply the determined control setpoint
        if target_heating_state:
            actual_control_setpoint = self._ot.get_control_setpoint()
            tolerance = self._config.get("OT", "SETPOINT_TOLERANCE")
            if abs(target_setpoint - actual_control_setpoint) > tolerance:
                logger.info(f"Applying Control Setpoint: {target_setpoint:.2f} (Previous: {actual_control_setpoint})")
                self._ot.set_control_setpoint(target_setpoint)
            else:
                logger.debug(f"Control Setpoint unchanged: {target_setpoint:.2f}")
        else:  # Heating is OFF, ensure control setpoint is low
            actual_control_setpoint = self._ot.get_control_setpoint()
            default_off_sp = self._config.get("OT", "DEFAULT_OFF_SETPOINT")
            tolerance = self._config.get("OT", "SETPOINT_TOLERANCE")
            if actual_control_setpoint is None or abs(actual_control_setpoint - default_off_sp) > tolerance:
                logger.info(f"Heating OFF, ensuring Control Setpoint is {default_off_sp} (was {actual_control_setpoint})")
                self._ot.set_control_setpoint(default_off_sp)
    
    def _check_override_flags(self):
        """Check and handle any override flags.
        
        Returns:
            tuple: (target_heating_state, override_active)
        """
        if self._force_on_next_cycle:
            logger.info("AutoHeat OVERRIDE: Forcing heating ON this cycle.")
            self._force_on_next_cycle = False  # Consume the flag
            return True, True
        elif self._force_off_next_cycle:
            logger.info("AutoHeat OVERRIDE: Forcing heating OFF this cycle.")
            self._force_off_next_cycle = False  # Consume the flag
            return False, True
        return None, False

    def _should_disable_heating(self, current_temp, avg_level):
        """Check if heating should be disabled based on temperature and valve levels.
        
        Args:
            current_temp: Current temperature reading
            avg_level: Average valve level
            
        Returns:
            bool: True if heating should be disabled
        """
        off_temp = self._config.get("AUTOH", "OFF_TEMP")
        off_valve = self._config.get("AUTOH", "OFF_VALVE_LEVEL")

        if current_temp is not None and current_temp >= off_temp:
            logger.info(f"AutoHeat: Condition met to disable heating (Temp {current_temp:.1f}C >= {off_temp:.1f}C)")
            return True
        elif avg_level is not None and avg_level < off_valve:
            logger.info(f"AutoHeat: Condition met to disable heating (Avg Valve {avg_level:.1f}% < {off_valve:.1f}%)")
            return True
        return False

    def _should_enable_heating(self, current_temp, avg_level):
        """Check if heating should be enabled based on temperature and valve levels.
        
        Args:
            current_temp: Current temperature reading
            avg_level: Average valve level
            
        Returns:
            bool: True if heating should be enabled
        """
        on_temp = self._config.get("AUTOH", "ON_TEMP")
        on_valve = self._config.get("AUTOH", "ON_VALVE_LEVEL")

        if current_temp is not None and avg_level is not None:
            if current_temp < on_temp and avg_level > on_valve:
                logger.info(f"AutoHeat: Condition met to enable heating (Temp {current_temp:.1f}C < {on_temp:.1f}C AND Avg Valve {avg_level:.1f}% > {on_valve:.1f}%)")
                return True
        elif current_temp is None and avg_level is not None and avg_level > on_valve:
            logger.info(f"AutoHeat: Enabling heating based on valve level ({avg_level:.1f}%) as temp is unavailable.")
            return True
        return False

    def _calculate_setpoint(self):
        """Calculate the final setpoint by combining PID and feedforward outputs.
        
        Returns:
            float: Calculated setpoint temperature
        """
        if not self._pid:
            logger.error("AutoHeat: PID instance is None, cannot calculate setpoint. Using default.")
            target_setpoint = self._config.get("OT", "MANUAL_HEATING_SETPOINT")
            logger.warning(f"Falling back to manual/default setpoint: {target_setpoint}")
            return target_setpoint

        # Get current conditions
        current_level = self._hm.avg_active_valve
        current_temp = self._hm.temperature if self._hm.temperature is not None else self._feedforward.base_temp_ref_outside
        current_wind = self._hm.wind_speed if self._hm.wind_speed is not None else 0.0
        current_sun = self._hm.illumination if self._hm.illumination is not None else 0.0
        
        # Calculate PID output
        pid_output = self._pid.update(current_level)
        logger.info(f"PID Update: current_level(valve)={current_level:.1f} -> BoilerTemp={pid_output:.2f}")
        
        # Calculate feedforward compensation
        ff_output = self._feedforward.calculate(current_wind, current_temp, current_sun)
        logger.info(f"FF Update: Wind={current_wind:.1f}, Temp={current_temp:.1f}, Sun={current_sun:.0f} -> Compensation={ff_output:.2f}")
        
        # Combine outputs
        final_output = pid_output + ff_output
        logger.info(f"Combined Output: PID={pid_output:.2f} + FF={ff_output:.2f} = {final_output:.2f}")
        
        # Apply output limits
        final_output = max(self._pid.get_output_min(), min(final_output, self._pid.get_output_max()))
        return final_output

    def _handle_auto_heating(self):
        """Determines target state and setpoint for Automatic Heating/PID mode."""
        logger.debug("MODE: Automatic Heating/PID")
        
        # Default values
        default_off_sp = self._config.get("OT", "DEFAULT_OFF_SETPOINT")
        target_heating_state = False
        target_setpoint = default_off_sp
        
        # Check for overrides
        override_state, override_active = self._check_override_flags()
        if override_active:
            target_heating_state = override_state
        else:
            # Get current state and readings
            current_ch_state = self._ot.is_ch_enabled()
            current_temp = self._hm.temperature
            avg_level = self._hm.avg_active_valve
            
            # Determine new state based on current conditions
            if current_ch_state and self._should_disable_heating(current_temp, avg_level):
                target_heating_state = False
            elif not current_ch_state and self._should_enable_heating(current_temp, avg_level):
                target_heating_state = True
            else:
                target_heating_state = current_ch_state  # Maintain current state
        
        # Calculate setpoint if heating should be on
        if target_heating_state:
            target_setpoint = self._calculate_setpoint()
        else:
            logger.debug(f"AutoHeat: Heating OFF. Target CS={default_off_sp}")
            
        return target_heating_state, target_setpoint

    def _handle_manual_heating(self):
        """Determines target state and setpoint for Manual Heating mode."""
        logger.debug("MODE: Manual Heating Control")
        
        default_off_sp = self._config.get("OT", "DEFAULT_OFF_SETPOINT")
        target_heating_state = False  # Default state is OFF
        target_setpoint = default_off_sp

        # Use _config.get directly for boolean
        manual_heating_desired = self._config.get("OT", "ENABLE_HEATING")
        target_heating_state = manual_heating_desired
        
        if target_heating_state:
            # Use _config.get directly for float
            manual_setpoint = self._config.get("OT", "MANUAL_HEATING_SETPOINT")
            target_setpoint = manual_setpoint  # Use Manual setpoint
            logger.info(f"ManualHeat: Heating ON. Target CS={target_setpoint:.2f}")
        else:
            logger.debug(f"ManualHeat: Heating OFF. Target CS={default_off_sp}")
            
        return target_heating_state, target_setpoint 