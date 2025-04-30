"""
PID Controller module for OT-PID-UI-PICO.

This module contains the PIDController class, which implements a standard
PID control algorithm with configurable gains and limits.
"""

import time
# Import the logger instance initialized elsewhere (e.g., in main or initialization)
from managers.manager_logger import Logger

logger = Logger()

# Detect if running in MicroPython-like environment with ticks_ms
_use_ticks_ms = hasattr(time, 'ticks_ms')

# Define a common tolerance for float comparisons within the class
_FLOAT_TOLERANCE = 1e-6

# Define a fallback for time.monotonic if not available
def _get_time():
    """Get current time in seconds."""
    if _use_ticks_ms:
        return time.ticks_ms() / 1000.0
    return time.time()  # Standard Python time in seconds

class PIDController:
    """
    A PID controller designed to regulate boiler water temperature based on
    the maximum eTRV valve opening (heating demand proxy).
    """
    def __init__(self, kp, ki, kd, setpoint, 
                 output_min, output_max, 
                 integral_accumulation_range,
                 valve_input_min, valve_input_max,
                 time_factor,
                 output_deadband):
        """Initialize the PID controller with control parameters."""
        # PID parameters
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.setpoint = setpoint 
        self.output_min = output_min
        self.output_max = output_max
        self.valve_input_min = valve_input_min
        self.valve_input_max = valve_input_max
        self.time_factor = time_factor
        self.output_deadband = output_deadband
        self.last_output = None
        self.last_applied_output = None

        # Calculate integral limits based on accumulation range
        if ki != 0:
            if integral_accumulation_range is None:
                integral_accumulation_range = (output_max - output_min) * 0.5
            self._integral_range = integral_accumulation_range / ki
            self._integral_min = -self._integral_range
            self._integral_max = self._integral_range
        else:
            self._integral_range = None
            self._integral_min = None
            self._integral_max = None

        # Validate input range
        if self.valve_input_min >= self.valve_input_max:
            raise ValueError("valve_input_min must be strictly less than valve_input_max")

        # Internal state variables
        self._integral = 0.0
        self._previous_error = 0.0
        self._last_time_ref = None

    def _calculate_pid(self, error, dt):
        """Calculate PID terms based on current error and time delta."""
        # Proportional term
        p_term = self.kp * error
        
        # Integral term
        if self.ki != 0:
            self._integral += error * dt
            # Apply integral limits if configured
            if self._integral_min is not None and self._integral_max is not None:
                self._integral = max(self._integral_min, min(self._integral, self._integral_max))
            i_term = self.ki * self._integral
        else:
            i_term = 0.0
        
        # Derivative term (on error)
        if dt > 0 and self.kd != 0:  # Avoid division by zero
            d_term = self.kd * (error - self._previous_error) / dt
        else:
            d_term = 0.0
        
        self._previous_error = error
        
        logger.debug(f"PID terms: Integral={self._integral:.3f}, P={p_term:.3f}, I={i_term:.3f}, D={d_term:.3f}")
        return p_term + i_term + d_term

    def update(self, current_level):
        """
        Update the controller state and calculate new output.
        
        Args:
            current_level (float): Current valve opening level (%)
            
        Returns:
            float: The calculated control output (target boiler temperature)
        """
        # Calculate time delta
        if _use_ticks_ms:
            current_time = time.ticks_ms()
        else:
            current_time = _get_time()
            
        if self._last_time_ref is None:
            self._last_time_ref = current_time
            return self.output_min  # Return minimum on first update
            
        if _use_ticks_ms:
            dt = time.ticks_diff(int(current_time), int(self._last_time_ref)) / 1000.0  # Convert to seconds
        else:
            dt = current_time - self._last_time_ref
        
        # Apply time factor (for simulation/testing)
        dt *= self.time_factor
        
        # Update time reference
        self._last_time_ref = current_time
        
        # Scale the input value to percentage
        if current_level < self.valve_input_min:
            scaled_input = 0.0
        elif current_level > self.valve_input_max:
            scaled_input = 100.0
        else:
            scaled_input = ((current_level - self.valve_input_min) / 
                          (self.valve_input_max - self.valve_input_min)) * 100.0
        
        # Calculate error
        error = self.setpoint - scaled_input
        
        # Calculate PID output
        pid_output = self._calculate_pid(error, dt)
        
        # Apply output limits #NOT TO THE PID ITSELF
        # self.last_output = max(self.output_min, min(pid_output, self.output_max))
        self.last_output = pid_output
        # Apply deadband to reduce unnecessary small changes  not to pid itself though #todo
        # if self.last_applied_output is not None:
        #     if abs(self.last_output - self.last_applied_output) <= self.output_deadband:
        #         return self.last_applied_output
        
        # self.last_applied_output = self.last_output
        return self.last_output

    # Getter methods
    def get_output_min(self): return self.output_min
    def get_output_max(self): return self.output_max

    # Setter methods for PID parameters
    def set_output_min(self, output_min):
        if abs(self.output_min - output_min) > _FLOAT_TOLERANCE:
            old_val = self.output_min
            self.output_min = output_min
            logger.info(f"PID output_min updated from {old_val} to: {output_min}")
            self._update_integral_limits()

    def set_output_max(self, output_max):
        if abs(self.output_max - output_max) > _FLOAT_TOLERANCE:
            old_val = self.output_max
            self.output_max = output_max
            logger.info(f"PID output_max updated from {old_val} to: {output_max}")
            self._update_integral_limits()

    def _update_integral_limits(self):
        """Update integral limits based on current settings."""
        if self.ki != 0 and self._integral_range is not None:
                default_integral_range = abs((self.output_max - self.output_min) * 0.5 / self.ki)
                if abs(self._integral_min - (-default_integral_range)) < _FLOAT_TOLERANCE and \
                   abs(self._integral_max - default_integral_range) < _FLOAT_TOLERANCE:
                    self._integral_min = -default_integral_range
                    self._integral_max = default_integral_range
                logger.info("Recalculated integral limits due to output range change.")

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
            if abs(self.ki) > _FLOAT_TOLERANCE:
                if self._integral_range is None:
                    self._integral_range = (self.output_max - self.output_min) * 0.5
                self._integral_range = self._integral_range / ki
                self._integral_min = -self._integral_range
                self._integral_max = self._integral_range
            else:
                self._integral = 0.0
                self._integral_range = None
                self._integral_min = None
                self._integral_max = None

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

    def set_output_deadband(self, deadband):
        """Sets the output deadband value."""
        if abs(self.output_deadband - deadband) > _FLOAT_TOLERANCE:
            logger.info(f"PID output_deadband updated from {self.output_deadband} to: {deadband}")
            self.output_deadband = deadband

    def set_integral_accumulation_range(self, range_value):
        """Sets the integral accumulation range in temperature units."""
        if self.ki == 0:
            logger.warning("Cannot set integral range when Ki=0")
            return

        if range_value is None:
            range_value = (self.output_max - self.output_min) * 0.5
            
        if abs(self._integral_range - range_value/self.ki) > _FLOAT_TOLERANCE:
            old_range = self._integral_range * self.ki if self._integral_range is not None else None
            self._integral_range = range_value / self.ki
            self._integral_min = -self._integral_range
            self._integral_max = self._integral_range
            logger.info(f"PID integral_range updated from {old_range} to: {range_value}")

    def reset(self):
        """Resets the controller's internal state."""
        self._integral = 0.0
        self._previous_error = 0.0
        self._last_time_ref = None
        self.last_output = None
        self.last_applied_output = None
        logger.info("PID controller state reset")

    def set_gains(self, kp, ki, kd):
        """Convenience method to set all gains at once."""
        self.set_kp(kp)
        self.set_ki(ki)
        self.set_kd(kd)

