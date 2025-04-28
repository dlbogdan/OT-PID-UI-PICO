import time
# Import the logger instance initialized elsewhere (e.g., in main or initialization)
from managers.manager_logger import Logger

logger = Logger()

# Detect if running in MicroPython-like environment with ticks_ms
_use_ticks_ms = hasattr(time, 'ticks_ms')

# Define a common tolerance for float comparisons within the class
_FLOAT_TOLERANCE = 1e-6

class PIDController:
    """
    A PID controller designed to regulate boiler water temperature based on
    the maximum eTRV valve opening (heating demand proxy) and feed-forward
    from weather conditions (wind, outside temperature, sun illumination).
    """
    def __init__(self, kp, ki, kd, setpoint=10.0, 
                 output_min=35.0, output_max=70.0, 
                 integral_min=None, integral_max=None,
                 ff_wind_coeff=0.1, ff_temp_coeff=1.0, ff_sun_coeff=0.0001,
                 ff_wind_interaction_coeff=0.005, # How much more wind matters when colder
                 base_temp_ref_outside=10.0, base_temp_boiler=41.0,
                 valve_input_min=0.0, valve_input_max=100.0, # Add valve input scaling limits
                 time_factor=1.0, # Simulation time acceleration factor
                 output_deadband=0.5): # Deadband for the output temperature
        """
        Initializes the PID controller.

        Args:
            kp (float): Proportional gain.
            ki (float): Integral gain.
            kd (float): Derivative gain.
            setpoint (float): Target maximum eTRV valve opening (%). Default: 40.0.
            output_min (float): Minimum boiler temperature output (deg C). Default: 30.0.
            output_max (float): Maximum boiler temperature output (deg C). Default: 80.0.
            integral_min (float, optional): Minimum limit for the integral term accumulator.
            integral_max (float, optional): Maximum limit for the integral term accumulator.
            ff_wind_coeff (float): Feed-forward coefficient for wind speed (degC per km/h).
            ff_temp_coeff (float): Feed-forward coefficient for outside temperature (degC per degC difference).
            ff_sun_coeff (float): Feed-forward coefficient for sun illumination (degC reduction per lux).
            ff_wind_interaction_coeff (float): Scales wind effect based on temp diff below reference.
            base_temp_ref_outside (float): Reference outside temperature (deg C) for base calculation.
            base_temp_boiler (float): Base boiler temperature (deg C) at reference outside temp.
            valve_input_min (float): Minimum value of the raw valve input to consider (scale starts here).
            valve_input_max (float): Maximum value of the raw valve input to consider (scale ends here).
            time_factor (float): Factor to accelerate time for simulation/tuning. Default: 1.0 (real-time).
            output_deadband (float): The +/- range around the last applied output. A new output is only applied if it differs by more than this amount. Default: 0.5.
        """
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.setpoint = setpoint 

        self.output_min = output_min
        self.output_max = output_max

        # Calculate default integral limits if not provided
        if ki != 0:
            default_integral_range = abs((output_max - output_min) * 0.5 / ki) # Ensure positive range
            self._integral_min = integral_min if integral_min is not None else -default_integral_range
            self._integral_max = integral_max if integral_max is not None else default_integral_range
        else:
            # If Ki is zero, integral limits are irrelevant unless explicitly set
            self._integral_min = integral_min 
            self._integral_max = integral_max

        # Feed-forward parameters
        self.ff_wind_coeff = ff_wind_coeff
        self.ff_temp_coeff = ff_temp_coeff
        self.ff_sun_coeff = ff_sun_coeff
        self.base_temp_ref_outside = base_temp_ref_outside
        self.base_temp_boiler = base_temp_boiler
        self.ff_wind_interaction_coeff = ff_wind_interaction_coeff # Store the new coefficient
        self.valve_input_min = valve_input_min
        self.valve_input_max = valve_input_max
        self.time_factor = time_factor # Store time factor
        self.output_deadband = output_deadband # Store the output deadband value
        self.last_output = None # Store the last calculated output (before deadband)
        self.last_applied_output = None # Store the last output value *after* applying the deadband

        # Validate input range
        if self.valve_input_min >= self.valve_input_max:
            raise ValueError("valve_input_min must be strictly less than valve_input_max")

        # Internal state variables
        self._integral = 0.0
        self._previous_error = 0.0
        self._last_time_ref = None # Reference point for dt calculation (ticks or monotonic seconds)

    def get_output_min(self):
        return self.output_min

    def get_output_max(self):
        return self.output_max

    def set_output_min(self, output_min):
        if abs(self.output_min - output_min) > _FLOAT_TOLERANCE:
            old_val = self.output_min
            self.output_min = output_min
            logger.info(f"PID output_min updated from {old_val} to: {output_min}")
            # Recalculate default integral limits if Ki is non-zero and limits were default
            # Note: This logic is simplified; assumes limits were default if they match calculation
            if self.ki != 0 and self._integral_min is not None and self._integral_max is not None:
                default_integral_range = abs((self.output_max - self.output_min) * 0.5 / self.ki)
                if abs(self._integral_min - (-default_integral_range)) < _FLOAT_TOLERANCE and \
                   abs(self._integral_max - default_integral_range) < _FLOAT_TOLERANCE:
                    self._integral_min = -default_integral_range
                    self._integral_max = default_integral_range
                    logger.info("Recalculated default integral limits due to output_min change.")

    def set_output_max(self, output_max):
        if abs(self.output_max - output_max) > _FLOAT_TOLERANCE:
            old_val = self.output_max
            self.output_max = output_max
            logger.info(f"PID output_max updated from {old_val} to: {output_max}")
            # Recalculate default integral limits similar to set_output_min
            if self.ki != 0 and self._integral_min is not None and self._integral_max is not None:
                default_integral_range = abs((self.output_max - self.output_min) * 0.5 / self.ki)
                if abs(self._integral_min - (-default_integral_range)) < _FLOAT_TOLERANCE and \
                   abs(self._integral_max - default_integral_range) < _FLOAT_TOLERANCE:
                    self._integral_min = -default_integral_range
                    self._integral_max = default_integral_range
                    logger.info("Recalculated default integral limits due to output_max change.")

    def set_kp(self, kp):
        """Sets the Proportional gain (Kp)."""
        if abs(self.kp - kp) > _FLOAT_TOLERANCE:
            logger.info(f"PID Kp updated from {self.kp} to: {kp}")
            self.kp = kp

    def set_ki(self, ki):
        """Sets the Integral gain (Ki)."""
        if abs(self.ki - ki) > _FLOAT_TOLERANCE:
            logger.info(f"PID Ki updated from {self.ki} to: {ki}")
            self.ki = ki
            # Potentially recalculate default integral limits if Ki changed significantly?
            # Or maybe reset integral term? Add logic here if needed.
            if self.ki == 0:
                 self._integral = 0.0 # Reset integral if Ki becomes 0

    def set_kd(self, kd):
        """Sets the Derivative gain (Kd)."""
        if abs(self.kd - kd) > _FLOAT_TOLERANCE:
            logger.info(f"PID Kd updated from {self.kd} to: {kd}")
            self.kd = kd

    def set_setpoint(self, setpoint):
        """Sets the target setpoint."""
        if abs(self.setpoint - setpoint) > _FLOAT_TOLERANCE:
            logger.info(f"PID Setpoint updated from {self.setpoint} to: {setpoint}")
            self.setpoint = setpoint

    def set_valve_input_min(self, valve_min):
        """Sets the minimum valve input value for scaling."""
        if valve_min >= self.valve_input_max:
            logger.error(f"Invalid valve_input_min ({valve_min}): must be < valve_input_max ({self.valve_input_max})")
            return
        if abs(self.valve_input_min - valve_min) > _FLOAT_TOLERANCE:
            logger.info(f"PID valve_input_min updated from {self.valve_input_min} to: {valve_min}")
            self.valve_input_min = valve_min

    def set_valve_input_max(self, valve_max):
        """Sets the maximum valve input value for scaling."""
        if valve_max <= self.valve_input_min:
            logger.error(f"Invalid valve_input_max ({valve_max}): must be > valve_input_min ({self.valve_input_min})")
            return
        if abs(self.valve_input_max - valve_max) > _FLOAT_TOLERANCE:
            logger.info(f"PID valve_input_max updated from {self.valve_input_max} to: {valve_max}")
            self.valve_input_max = valve_max

    def set_ff_wind_coeff(self, coeff):
        """Sets the feed-forward coefficient for wind speed."""
        if abs(self.ff_wind_coeff - coeff) > _FLOAT_TOLERANCE:
            logger.info(f"PID ff_wind_coeff updated from {self.ff_wind_coeff} to: {coeff}")
            self.ff_wind_coeff = coeff

    def set_ff_temp_coeff(self, coeff):
        """Sets the feed-forward coefficient for outside temperature."""
        if abs(self.ff_temp_coeff - coeff) > _FLOAT_TOLERANCE:
            logger.info(f"PID ff_temp_coeff updated from {self.ff_temp_coeff} to: {coeff}")
            self.ff_temp_coeff = coeff

    def set_ff_sun_coeff(self, coeff):
        """Sets the feed-forward coefficient for sun illumination."""
        if abs(self.ff_sun_coeff - coeff) > _FLOAT_TOLERANCE:
            logger.info(f"PID ff_sun_coeff updated from {self.ff_sun_coeff} to: {coeff}")
            self.ff_sun_coeff = coeff

    def set_ff_wind_interaction_coeff(self, coeff):
        """Sets the feed-forward coefficient for wind/temperature interaction."""
        if abs(self.ff_wind_interaction_coeff - coeff) > _FLOAT_TOLERANCE:
            logger.info(f"PID ff_wind_interaction_coeff updated from {self.ff_wind_interaction_coeff} to: {coeff}")
            self.ff_wind_interaction_coeff = coeff

    def set_base_temp_ref_outside(self, temp):
        """Sets the base reference outside temperature."""
        if abs(self.base_temp_ref_outside - temp) > _FLOAT_TOLERANCE:
            logger.info(f"PID base_temp_ref_outside updated from {self.base_temp_ref_outside} to: {temp}")
            self.base_temp_ref_outside = temp

    def set_base_temp_boiler(self, temp):
        """Sets the base boiler temperature reference."""
        if abs(self.base_temp_boiler - temp) > _FLOAT_TOLERANCE:
            logger.info(f"PID base_temp_boiler updated from {self.base_temp_boiler} to: {temp}")
            self.base_temp_boiler = temp

    def set_output_deadband(self, deadband):
        """Sets the output deadband value."""
        if deadband < 0:
            logger.error(f"Invalid output_deadband ({deadband}): must be non-negative.")
            return
        if abs(self.output_deadband - deadband) > _FLOAT_TOLERANCE:
            logger.info(f"PID output_deadband updated from {self.output_deadband} to: {deadband}")
            self.output_deadband = deadband

    def _calculate_feed_forward(self, wind_speed, outside_temp, sun_illumination):
        """Calculates the feed-forward base boiler temperature, including wind interaction."""
        # Temperature adjustment (colder outside -> higher boiler temp)
        temp_diff_base = self.base_temp_ref_outside - outside_temp
        temp_adjustment = self.ff_temp_coeff * (self.base_temp_ref_outside - outside_temp)

        # Base wind adjustment (effect independent of temp diff, or at reference temp)
        base_wind_adjustment = self.ff_wind_coeff * wind_speed

        logger.debug(f"FF Calc: BaseTemp={self.base_temp_boiler:.2f}, RefOutside={self.base_temp_ref_outside:.1f}")
        logger.debug(f"FF Calc: OutsideTemp={outside_temp:.1f}, TempDiff={temp_diff_base:.1f} -> TempAdj={temp_adjustment:.2f}")

        # Interaction wind adjustment (extra effect when colder than reference)
        # Only applies when outside_temp < base_temp_ref_outside
        temp_diff_for_wind = max(0, self.base_temp_ref_outside - outside_temp)
        interaction_adjustment = self.ff_wind_interaction_coeff * wind_speed * temp_diff_for_wind

        logger.debug(f"FF Calc: WindSpeed={wind_speed:.1f}, BaseWindAdj={base_wind_adjustment:.2f}, InteractionAdj={interaction_adjustment:.2f}")

        total_wind_adjustment = base_wind_adjustment + interaction_adjustment

        # Sun adjustment (more sun -> lower boiler temp)
        # Use max(0, ...) to prevent negative sun adjustment if coeff is negative
        sun_reduction = max(0, self.ff_sun_coeff * sun_illumination) 
        sun_adjustment = -sun_reduction

        logger.debug(f"FF Calc: SunIllum={sun_illumination:.0f}, SunReduction={sun_reduction:.2f}")

        # Combine base, adjustments
        ff_base_temp = self.base_temp_boiler + temp_adjustment + total_wind_adjustment + sun_adjustment
        
        logger.debug(f"FF Calc: Final FF Base Temp = {ff_base_temp:.2f}")
        return ff_base_temp

    def update(self, current_level, wind_speed, outside_temp, sun_illumination):
        """
        Calculates the required boiler temperature based on current conditions.
        Uses time.ticks_ms() for time calculation.
        Scales the valve input based on valve_input_min/max settings.
        """
        output_temp = self.output_min # Default to min output in case of error
        try:
            # --- Input Scaling --- 
            # Clamp the raw input valve value to the configured min/max range
            clamped_valve = max(self.valve_input_min, min(current_level, self.valve_input_max))
            
            # Scale the clamped value from [min, max] to [0, 100] for PID calculation
            input_range = self.valve_input_max - self.valve_input_min
            # We already validated input_range > 0 in __init__
            scaled_valve_for_pid = ((clamped_valve - self.valve_input_min) / input_range) * 100.0
            # --- End Input Scaling ---
            
            # --- Time Calculation (Portable) ---
            dt = 1.0 # Default dt for first run or error cases
            current_time_ref = None

            if _use_ticks_ms:
                current_time_ref = time.ticks_ms()
                if self._last_time_ref is not None:
                    # Calculate dt in seconds using ticks_diff (handles wrap-around)
                    dt = time.ticks_diff(current_time_ref, self._last_time_ref) / 1000.0
            else: # Assume standard Python, use time.monotonic()
                current_time_ref = time.monotonic() # type: ignore # Returns seconds
                if self._last_time_ref is not None:
                    dt = current_time_ref - self._last_time_ref
            
            # Prevent issues with zero or negative dt (can happen with very fast calls)
            if dt <= 0:
                dt = 1e-6 
            
            # Apply time acceleration factor for simulation
            simulated_dt = dt * self.time_factor
            
            self._last_time_ref = current_time_ref # Store current time reference for the next calculation
            # --- End Time Calculation ---

            # Error: Positive error means valve opening is higher than target -> need more heat
            # Use the scaled valve value for error calculation
            error = scaled_valve_for_pid - self.setpoint 
            logger.debug(f"PID Calc: Error = ScaledValve({scaled_valve_for_pid:.2f}) - Setpoint({self.setpoint:.2f}) = {error:.2f}")

            # Proportional term
            p_term = self.kp * error
            if self.output_min < output_temp < self.output_max: #anti-windup todo: do we really need this?
             # Integral term with anti-windup (Corrected Logic)
                 self._integral += error * simulated_dt # Update internal integral state first
             # else: # Potentially log why integral wasn't updated (anti-windup active)
             #    logger.debug("PID Calc: Anti-windup active, integral not updated.")
            
            # Clamp the accumulated integral state
            if self._integral_max is not None:
                self._integral = min(self._integral, self._integral_max)
            if self._integral_min is not None:
                self._integral = max(self._integral, self._integral_min)
                
            logger.debug(f"PID Calc: Integral Accumulator = {self._integral:.4f}")
                
            # Calculate I term based on the clamped integral state
            i_term = self.ki * self._integral 

            # Derivative term
            d_term = 0.0
            # Calculate derivative only if dt is valid and reasonable (e.g., < 5s)
            # Avoids derivative kick on first run or after long pauses
            if self._last_time_ref is not None and 0 < simulated_dt < (5.0 * self.time_factor):
                 # Calculate derivative using simulated time delta
                 derivative = (error - self._previous_error) / simulated_dt 
                 d_term = self.kd * derivative
            
            logger.debug(f"PID Calc: P={p_term:.2f}, I={i_term:.2f}, D={d_term:.2f} (dt={simulated_dt:.3f}s)")
            
            # Calculate base temperature from feed-forward
            ff_base_temp = self._calculate_feed_forward(wind_speed, outside_temp, sun_illumination)

            # Calculate PID adjustment 
            pid_adjustment = p_term + i_term + d_term

            # Final output: Base temperature adjusted by PID
            output_temp = ff_base_temp + pid_adjustment

            logger.debug(f"PID Calc: Raw Output (Pre-Clamp) = FF({ff_base_temp:.2f}) + PIDAdj({pid_adjustment:.2f}) = {output_temp:.2f}")

            # Final clamping of the combined result:
            output_temp = max(self.output_min, min(self.output_max, output_temp))

            # Update state for next iteration - BEFORE assigning last_output
            self._previous_error = error
            
            # Store the calculated output *before* applying the deadband
            self.last_output = output_temp

            # --- Apply Deadband --- 
            if self.last_applied_output is None:
                 # First run or after reset, apply the output directly
                # Round to nearest 0.5 before applying
                self.last_applied_output = round(output_temp * 2) / 2
            else:
                # Check if the change exceeds the deadband
                if abs(output_temp - self.last_applied_output) > self.output_deadband:
                    # Round to nearest 0.5 before applying the new value
                    self.last_applied_output = round(output_temp * 2) / 2
                    logger.debug(f"PID output changed to {self.last_applied_output:.2f} (raw: {output_temp:.2f})")
                # else: keep self.last_applied_output as it is
            # --- End Deadband --- 

        except Exception as e:
            # Log any error occurring *within* the PID update calculation
            logger.error(f"Error within PIDController.update: {e}")
            # self.last_output remains unchanged (or None if error on first run)
            # Return the safe default value
            # return self.output_min # Already assigned at the start

        # Return the output *after* applying the deadband
        return self.last_applied_output

    def reset(self):
        """Resets the PID controller's internal state."""
        self._integral = 0.0
        self._previous_error = 0.0
        self._last_time_ref = None # Reset time reference
        self.last_output = None # Reset last calculated output
        self.last_applied_output = None # Reset last applied output for deadband
        print("PID controller reset.")

    def set_gains(self, kp, ki, kd):
        """Allows updating PID gains dynamically."""
        self.set_kp(kp)
        self.set_ki(ki)
        self.set_kd(kd)
        # Note: set_gains now uses individual setters, logging is handled there.
        # Keep the print for overall confirmation if desired, or remove.
        # print(f"PID gains updated via set_gains: Kp={kp}, Ki={ki}, Kd={kd}")

