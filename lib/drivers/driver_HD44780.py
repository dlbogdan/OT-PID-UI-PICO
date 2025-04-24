#driver_HD44780.py - Driver for HD44780 LCD using any Pin-compatible interface
import utime
from drivers.driver_lcd import LCD
from managers.manager_logger import Logger

logger = Logger()

# --- CGRAM/DDRAM Constants ---
LCD_SETCGRAMADDR = 0x40
LCD_SETDDRAMADDR = 0x80


# --- LCD Class Definition --- 
class LCD1602(LCD):
    def __init__(self, rw_pin, rs_pin, en_pin, d4_pin, d5_pin, d6_pin, d7_pin, cols=16, rows=2):
        """Initialize with Pin-compatible objects for each LCD pin."""
        super().__init__(cols, rows)
        self.rw_pin = rw_pin
        self.rs_pin = rs_pin
        self.en_pin = en_pin
        self.data_pins = [d4_pin, d5_pin, d6_pin, d7_pin]

        # Initialize display hardware
        self._init_display()

        # --- Load all defined custom characters ---
        self.load_custom_chars()

    def _write_nibble(self, nibble, rs):
        self.rs_pin.value(rs)
        for i, pin in enumerate(self.data_pins):
            pin.value((nibble & (1 << i)) != 0)
        # Pulse Enable
        self.en_pin.value(1)
        utime.sleep_us(1)
        self.en_pin.value(0)
        utime.sleep_us(40) # Command execution time

    def _send(self, data, rs):
        """Send command (rs=0) or data (rs=1) in 4-bit mode."""
        self._write_nibble((data >> 4) & 0x0F, rs)  # High nibble
        self._write_nibble(data & 0x0F, rs)         # Low nibble

    def _init_display(self):
        """Initializes the display in 4-bit mode."""
        self.rw_pin.value(0) # Set Write mode
        utime.sleep_ms(50)
        self._write_nibble(0x03, 0); utime.sleep_ms(5)
        self._write_nibble(0x03, 0); utime.sleep_us(150)
        self._write_nibble(0x03, 0); utime.sleep_us(150)
        self._write_nibble(0x02, 0); utime.sleep_us(100) # Set 4-bit mode
        self._send(0x28, 0)  # Function Set: 4-bit, 2 lines, 5x8 font
        self._send(0x0C, 0)  # Display Control: Display ON, Cursor OFF, Blink OFF
        self._send(0x01, 0); utime.sleep_ms(2) # Clear Display
        self._send(0x06, 0)  # Entry Mode Set: Increment cursor, No shift
        self._send(LCD_SETDDRAMADDR | 0x00, 0) # Cursor Home

    def clear(self):
        """Clears the display and returns cursor to home."""
        self._send(0x01, 0)
        utime.sleep_ms(2)

    def set_cursor(self, col, row):
        """Moves the cursor to the specified column and row."""
        row_offsets = [0x00, 0x40]
        if row < self.rows and col < self.cols:
            address = col + row_offsets[row]
            self._send(LCD_SETDDRAMADDR | address, 0)

    def write_text(self, text):
        """Writes a string of text at the current cursor position."""
        for char in text:
            self._send(ord(char), 1)

    def show_cursor(self, show):
        """Shows or hides the cursor (underline)."""
        self._send(0x0E if show else 0x0C, 0)

    def blink_cursor(self, blink):
        """Turns the blinking block cursor on or off."""
        # Requires cursor ON (use show_cursor(True) first)
        self._send(0x0F if blink else 0x0E, 0)

    # --- Method to define a SINGLE custom character ---
    def define_custom_char(self, char_code, pattern_bytes):
        """
        Defines a custom character in CGRAM.

        Args:
            char_code (int): The code (0-7) for the character.
            pattern_bytes (list[int]): A list of 8 bytes representing the 5x8 pattern.
        """
        if not (0 <= char_code <= 7):
            logger.error("Custom character code must be 0-7."); return
        if len(pattern_bytes) != 8:
            logger.error("Custom character pattern must be 8 bytes."); return

        cgram_addr = LCD_SETCGRAMADDR | (char_code << 3)
        self._send(cgram_addr, 0) # Set CGRAM address
        utime.sleep_us(50)
        for byte_val in pattern_bytes: # Write pattern bytes
            self._send(byte_val & 0x1F, 1)
        # Set DDRAM address back after writing to CGRAM
        self._send(LCD_SETDDRAMADDR | 0x00, 0) # Go home

    # --- NEW: Method to load all chars from the static list ---
    

