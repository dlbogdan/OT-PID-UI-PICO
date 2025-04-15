#driver_rgbled.py - Driver for RGB LED using any Pin-compatible interface
import utime

class RGBLED:
    def __init__(self, red_pin, green_pin, blue_pin, initial_color="black"):
        """Initialize the RGB LED with Pin-compatible objects for each color."""
        self.red_pin = red_pin
        self.green_pin = green_pin
        self.blue_pin = blue_pin
        
        self.last_heartbeat = 0
        self.led_is_on = False
        self.blink = False
        self.color = "black"
        self.blink_duration = 1000  # Default blink duration in milliseconds

        # Set initial state to initial color
        self.direct_send_color(initial_color)

    def set_color(self, color_name, blink=False, duration_on=1000, duration_off=1000):
        self.blink = blink
        self.blink_duration_off = duration_off
        self.blink_duration_on = duration_on
        self.color = color_name
        color_name = color_name.lower()

    def direct_send_color(self, color_name="black"):  # used internally but also if you want to send a color directly to the led outside the main loop
        """Set the LED to the specified color by name."""
        # Convert to lowercase for case-insensitive input
        
        # Map of color names to pin values (red, blue, green)
        # 0 = ON, 1 = OFF due to inverted logic
        color_map = {
            "black": (1, 1, 1),   # All off
            "red": (0, 1, 1),     # Red on
            "green": (1, 1, 0),   # Green on
            "blue": (1, 0, 1),    # Blue on
            "yellow": (0, 1, 0),  # Red and green on
            "magenta": (0, 0, 1), # Red and blue on
            "cyan": (1, 0, 0),    # Green and blue on
            "white": (0, 0, 0)    # All on
        }

        # Check if the color name is valid
        if color_name not in color_map:
            raise ValueError(f"Invalid color name: {color_name}")

        # Get the pin values for the specified color
        red_val, blue_val, green_val = color_map[color_name]

        # Write the values to the respective pins
        self.red_pin.value(red_val)
        self.blue_pin.value(blue_val)
        self.green_pin.value(green_val)

    def update(self):
        """Blink the LED or have it light up solidly with the specified color."""
        if self.blink:
            if self.led_is_on:
                if (utime.ticks_ms() - self.last_heartbeat) > self.blink_duration_on:
                    self.direct_send_color("black")
                    self.led_is_on = False
                    self.last_heartbeat = utime.ticks_ms()
            else:
                if (utime.ticks_ms() - self.last_heartbeat) > self.blink_duration_off:
                    # Reset the last heartbeat time
                    self.last_heartbeat = utime.ticks_ms()
                    # Set the color
                    self.direct_send_color(self.color)
                    # Wait for the duration
                    self.led_is_on = True
        else:
            # If not blinking, just set the color
            self.direct_send_color(self.color)
            self.led_is_on = True