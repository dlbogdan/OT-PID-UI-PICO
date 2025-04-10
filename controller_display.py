from driver_lcd import LCD
import time



class DisplayController:
    def __init__(self, lcd: LCD):
        """Initialize with an LCD instance."""
        self.lcd = lcd
        self.cols = self.lcd.cols
        self.rows = self.lcd.rows
        self._buffer = [" " * self.cols for _ in range(self.rows)]
        self.clear()

    def _pad(self, text, length):
        """Pad or truncate a string to exactly `length` characters."""
        s = str(text)
        if len(s) < length:
            s = s + (" " * (length - len(s)))
        return s[:length]
    
    def clear(self):
        self.lcd.clear()
        self._buffer = [" " * self.cols for _ in range(self.rows)]
    
    def show_message(self, *lines):
        # Pad all lines to the correct length
        padded_lines = [self._pad(line, self.cols) for line in lines]
        # Fill remaining lines with spaces if not enough lines provided
        while len(padded_lines) < self.rows:
            padded_lines.append(" " * self.cols)
        
        # Compare and update each line
        for row in range(self.rows):
            current_line = padded_lines[row]
            buffer_line = self._buffer[row]
            col = 0
            
            while col < self.cols:
                # Find the next character that differs
                while col < self.cols and current_line[col] == buffer_line[col]:
                    col += 1
                
                if col < self.cols:
                    # Found a difference, now find how many consecutive characters differ
                    start_col = col
                    while col < self.cols and current_line[col] != buffer_line[col]:
                        col += 1
                    
                    # Write the chunk of changed characters
                    self.lcd.set_cursor(start_col, row)
                    self.lcd.write_text(current_line[start_col:col])
        
        # Update buffer with new text
        self._buffer = padded_lines[:self.rows]

    # def update_status_icons(self, wifi_connected, valve_connected, boiler_connected, blink_wifi=False, ccu_connected=None):
    #     """Draw status icons in fixed positions: boiler [col-3], valve [col-2], wifi [col-1]."""
    #     row = self.rows - 1

    #     # Determine which character pattern to use based on status
    #     char_index = 0  # Default: all nok
    #     if wifi_connected and not valve_connected and not boiler_connected:
    #         char_index = 1
    #     elif not wifi_connected and valve_connected and not boiler_connected:
    #         char_index = 2
    #     elif not wifi_connected and not valve_connected and boiler_connected:
    #         char_index = 3
    #     elif wifi_connected and not valve_connected and boiler_connected:
    #         char_index = 4
    #     elif not wifi_connected and valve_connected and boiler_connected:
    #         char_index = 5
    #     elif wifi_connected and valve_connected and boiler_connected:
    #         char_index = 6

    #     # Update character 2 with the selected pattern
    #     self.lcd.define_custom_char(2, DYNAMIC_CUSTOM_CHARS[char_index])

    #     # Display the status character
    #     self.lcd.set_cursor(self.cols - 1, row)
    #     self.lcd.write_text(chr(2))

    def update_custom_char(self, char_index, pattern):
        self.lcd.define_custom_char(char_index, pattern)

    def show_cursor(self, show):
        self.lcd.show_cursor(show)

    def show_cursor_pos(self, show, col,lin):
        self.lcd.set_cursor(col,lin)
        self.lcd.show_cursor(show)

    def load_custom_chars(self, custom_chars):
        """Loads all defined custom characters from CUSTOM_CHARS list into CGRAM."""
        print("Loading custom characters to CGRAM...")
        # Ensure we don't try to load more than 8
        num_chars_to_load = min(len(custom_chars), 8)
        for i in range(num_chars_to_load):
             pattern = custom_chars[i]
             if pattern and len(pattern) == 8: # Basic check for valid pattern
                 self.lcd.define_custom_char(i, pattern)
             else:
                  print(f"Warning: Invalid pattern defined for custom char {i}. Skipping.")
        print(f"Loaded {num_chars_to_load} custom characters.")
        # Ensure DDRAM address is reset after loading all chars
        self.lcd.set_cursor(0,0)