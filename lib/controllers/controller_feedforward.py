"""
Feedforward Controller module for OT-PID-UI-PICO.

This module contains the FeedforwardController class, which handles
weather compensation calculations for the heating system.
"""

from managers.manager_logger import Logger

logger = Logger()

# Define a common tolerance for float comparisons
_FLOAT_TOLERANCE = 1e-6

class FeedforwardController:
    """Handles feed-forward calculations for weather compensation."""
    
    def __init__(self, wind_coeff, temp_coeff, sun_coeff,
                 wind_chill_coeff, base_temp_ref_outside,
                 base_temp_boiler):
        """
        Initialize the feed-forward controller.
        
        Args:
            wind_coeff (float): Feed-forward coefficient for wind speed (degC per km/h)
            temp_coeff (float): Feed-forward coefficient for outside temperature (degC per degC difference)
            sun_coeff (float): Feed-forward coefficient for sun illumination (degC reduction per lux)
            wind_chill_coeff (float): Scales wind effect based on temp diff below reference
            base_temp_ref_outside (float): Reference outside temperature (deg C) for base calculation
            base_temp_boiler (float): Base boiler temperature (deg C) at reference outside temp
        """
        self.wind_coeff = wind_coeff
        self.temp_coeff = temp_coeff
        self.sun_coeff = sun_coeff
        self.wind_chill_coeff = wind_chill_coeff
        self.base_temp_ref_outside = base_temp_ref_outside
        self.base_temp_boiler = base_temp_boiler
    
    def calculate(self, wind_speed, outside_temp, sun_illumination):
        """
        Calculate the feed-forward compensation based on weather conditions.
        
        Args:
            wind_speed (float): Current wind speed in km/h
            outside_temp (float): Current outside temperature in °C
            sun_illumination (float): Current sun illumination in lux
            
        Returns:
            float: The calculated feed-forward compensation value in °C
        """
        # Base temperature adjustment from outside temperature difference
        temp_diff = self.base_temp_ref_outside - outside_temp
        temp_compensation = temp_diff * self.temp_coeff
        
        # Enhanced wind compensation based on temperature difference
        wind_effect = wind_speed * self.wind_coeff
        if temp_diff > 0:  # Only enhance wind effect when colder than reference
            wind_effect *= (1.0 + temp_diff * self.wind_chill_coeff)
            
        # Solar gain compensation (reduces required temperature)
        sun_compensation = -(sun_illumination * self.sun_coeff)
        
        # Combine all effects
        ff_output = self.base_temp_boiler + temp_compensation + wind_effect + sun_compensation
        
        logger.debug(f"FF Calc: Temp={temp_compensation:.2f}, Wind={wind_effect:.2f}, Sun={sun_compensation:.2f}")
        return ff_output
    
    def set_wind_coeff(self, coeff):
        """Sets the feed-forward coefficient for wind speed."""
        if abs(self.wind_coeff - coeff) > _FLOAT_TOLERANCE:
            logger.info(f"FF wind_coeff updated from {self.wind_coeff} to: {coeff}")
            self.wind_coeff = coeff

    def set_temp_coeff(self, coeff):
        """Sets the feed-forward coefficient for outside temperature."""
        if abs(self.temp_coeff - coeff) > _FLOAT_TOLERANCE:
            logger.info(f"FF temp_coeff updated from {self.temp_coeff} to: {coeff}")
            self.temp_coeff = coeff

    def set_sun_coeff(self, coeff):
        """Sets the feed-forward coefficient for sun illumination."""
        if abs(self.sun_coeff - coeff) > _FLOAT_TOLERANCE:
            logger.info(f"FF sun_coeff updated from {self.sun_coeff} to: {coeff}")
            self.sun_coeff = coeff

    def set_wind_chill_coeff(self, coeff):
        """Sets the wind chill interaction coefficient."""
        if abs(self.wind_chill_coeff - coeff) > _FLOAT_TOLERANCE:
            logger.info(f"FF wind_chill_coeff updated from {self.wind_chill_coeff} to: {coeff}")
            self.wind_chill_coeff = coeff

    def set_base_temp_ref_outside(self, temp):
        """Sets the reference outside temperature."""
        if abs(self.base_temp_ref_outside - temp) > _FLOAT_TOLERANCE:
            logger.info(f"FF base_temp_ref_outside updated from {self.base_temp_ref_outside} to: {temp}")
            self.base_temp_ref_outside = temp

    def set_base_temp_boiler(self, temp):
        """Sets the base boiler temperature."""
        if abs(self.base_temp_boiler - temp) > _FLOAT_TOLERANCE:
            logger.info(f"FF base_temp_boiler updated from {self.base_temp_boiler} to: {temp}")
            self.base_temp_boiler = temp 