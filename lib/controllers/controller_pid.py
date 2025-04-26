import time
# Import the logger instance initialized elsewhere (e.g., in main or initialization)
from managers.manager_logger import Logger

logger = Logger()

# Detect if running in MicroPython-like environment with ticks_ms
_use_ticks_ms = hasattr(time, 'ticks_ms')

class PIDController:
    """
    A PID controller designed to regulate boiler water temperature based on
    the maximum eTRV valve opening (heating demand proxy) and feed-forward
    from weather conditions (wind, outside temperature, sun illumination).
    """
    def __init__(self, kp, ki, kd, setpoint=40.0, 
                 output_min=30.0, output_max=80.0, 
                 integral_min=None, integral_max=None,
                 ff_wind_coeff=0.1, ff_temp_coeff=1.0, ff_sun_coeff=0.0001,
                 ff_wind_interaction_coeff=0.005, # How much more wind matters when colder
                 base_temp_ref_outside=10.0, base_temp_boiler=45.0,
                 valve_input_min=0.0, valve_input_max=100.0, # Add valve input scaling limits
                 time_factor=1.0): # Simulation time acceleration factor
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

        # Validate input range
        if self.valve_input_min >= self.valve_input_max:
            raise ValueError("valve_input_min must be strictly less than valve_input_max")

        # Internal state variables
        self._integral = 0.0
        self._previous_error = 0.0
        self._last_time_ref = None # Reference point for dt calculation (ticks or monotonic seconds)
        self.last_output = None # Store the last calculated output

    def get_output_min(self):
        return self.output_min

    def get_output_max(self):
        return self.output_max

    def set_output_min(self, output_min):
        self.output_min = output_min

    def set_output_max(self, output_max):
        self.output_max = output_max

    def _calculate_feed_forward(self, wind_speed, outside_temp, sun_illumination):
        """Calculates the feed-forward base boiler temperature, including wind interaction."""
        # Temperature adjustment (colder outside -> higher boiler temp)
        temp_adjustment = self.ff_temp_coeff * (self.base_temp_ref_outside - outside_temp)

        # Base wind adjustment (effect independent of temp diff, or at reference temp)
        base_wind_adjustment = self.ff_wind_coeff * wind_speed

        # Interaction wind adjustment (extra effect when colder than reference)
        # Only applies when outside_temp < base_temp_ref_outside
        temp_diff_for_wind = max(0, self.base_temp_ref_outside - outside_temp)
        interaction_adjustment = self.ff_wind_interaction_coeff * wind_speed * temp_diff_for_wind

        total_wind_adjustment = base_wind_adjustment + interaction_adjustment

        # Sun adjustment (more sun -> lower boiler temp)
        sun_adjustment = -self.ff_sun_coeff * sun_illumination

        # Combine base, adjustments
        ff_base_temp = self.base_temp_boiler + temp_adjustment + total_wind_adjustment + sun_adjustment
        
        return ff_base_temp

    def update(self, current_max_valve, wind_speed, outside_temp, sun_illumination):
        """
        Calculates the required boiler temperature based on current conditions.
        Uses time.ticks_ms() for time calculation.
        Scales the valve input based on valve_input_min/max settings.
        """
        output_temp = self.output_min # Default to min output in case of error
        try:
            # --- Input Scaling --- 
            # Clamp the raw input valve value to the configured min/max range
            clamped_valve = max(self.valve_input_min, min(current_max_valve, self.valve_input_max))
            
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

            # Proportional term
            p_term = self.kp * error

            # Integral term with anti-windup (Corrected Logic)
            self._integral += error * simulated_dt # Update internal integral state first
            
            # Clamp the accumulated integral state
            if self._integral_max is not None:
                self._integral = min(self._integral, self._integral_max)
            if self._integral_min is not None:
                self._integral = max(self._integral, self._integral_min)
                
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
           
            # Calculate base temperature from feed-forward
            ff_base_temp = self._calculate_feed_forward(wind_speed, outside_temp, sun_illumination)

            # Calculate PID adjustment 
            pid_adjustment = p_term + i_term + d_term

            # Final output: Base temperature adjusted by PID
            output_temp = ff_base_temp + pid_adjustment

            # Final clamping of the combined result:
            output_temp = max(self.output_min, min(self.output_max, output_temp))

            # Update state for next iteration - BEFORE assigning last_output
            self._previous_error = error
            
            # Assign last output just before returning successfully
            self.last_output = output_temp 

        except Exception as e:
            # Log any error occurring *within* the PID update calculation
            logger.error(f"Error within PIDController.update: {e}")
            # self.last_output remains unchanged (or None if error on first run)
            # Return the safe default value
            # return self.output_min # Already assigned at the start

        # Return the calculated (or default if error) temperature
        return output_temp

    def reset(self):
        """Resets the PID controller's internal state."""
        self._integral = 0.0
        self._previous_error = 0.0
        self._last_time_ref = None # Reset time reference
        self.last_output = None # Reset last output as well
        print("PID controller reset.")

    def set_gains(self, kp, ki, kd):
        """Allows updating PID gains dynamically."""
        self.kp = kp
        self.ki = ki
        self.kd = kd
        # Note: Does not automatically recalculate integral limits if they were manually set.
        # If default limits were used, they might become suboptimal if Ki changes drastically.
        print(f"PID gains updated: Kp={kp}, Ki={ki}, Kd={kd}")

