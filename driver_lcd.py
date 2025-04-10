#driver_lcd.py - Base class for LCD displays.

import utime

class LCD:
    def __init__(self, cols, rows):
        """Base class for LCD displays.
        
        Args:
            cols (int): Number of columns in the display
            rows (int): Number of rows in the display
        """
        self.cols = cols
        self.rows = rows

    def clear(self):
        """Clears the display and returns cursor to home."""
        raise NotImplementedError("Subclasses must implement clear()")

    def set_cursor(self, col, row):
        """Moves the cursor to the specified column and row.
        
        Args:
            col (int): Column position (0-based)
            row (int): Row position (0-based)
        """
        raise NotImplementedError("Subclasses must implement set_cursor()")

    def write_text(self, text):
        """Writes a string of text at the current cursor position.
        
        Args:
            text (str): Text to write to the display
        """
        raise NotImplementedError("Subclasses must implement write_text()")

    def show_cursor(self, show):
        """Shows or hides the cursor (underline).
        
        Args:
            show (bool): True to show cursor, False to hide
        """
        raise NotImplementedError("Subclasses must implement show_cursor()")

    def blink_cursor(self, blink):
        """Turns the blinking block cursor on or off.
        
        Args:
            blink (bool): True to enable blinking, False to disable
        """
        #raise NotImplementedError("Subclasses must implement blink_cursor()")
        pass

    def define_custom_char(self, char_code, pattern_bytes):
        """Defines a custom character in CGRAM.
        
        Args:
            char_code (int): The code (0-7) for the character
            pattern_bytes (list[int]): A list of 8 bytes representing the pattern
        """
        #raise NotImplementedError("Subclasses must implement define_custom_char()")
        pass

    def load_custom_chars(self):
        """Loads all defined custom characters into CGRAM."""
        #raise NotImplementedError("Subclasses must implement load_custom_chars()") 
        pass
