from drivers.driver_lcd import LCD
import time
from machine import Timer



class DisplayController:
    def __init__(self, lcd: LCD):
        """Initialize with an LCD instance."""
        self.lcd = lcd
        self.cols = self.lcd.cols
        self.rows = self.lcd.rows
        self._scroll_positions = {}  # {row: position}
        self._scroll_timestamps = {}  # {row: last_update_time}
        self._original_texts = {}  # {row: original_text}
        self._scroll_timer = None    # Timer for auto-scrolling
        self._scroll_refresh = 30
        self._scroll_period = 300
        self._scroll_wait = 1000
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
        self._scroll_positions = {}
        self._scroll_timestamps = {}
        self._original_texts = {}
        self._stop_scroll_timer()
    
    def _stop_scroll_timer(self):
        """Stop the scrolling timer if active."""
        if self._scroll_timer:
            try:
                self._scroll_timer.deinit()
            except:
                pass
            self._scroll_timer = None
    
    def _start_scroll_timer(self):
        """Start a timer to update scrolling text every 30ms."""
        if not self._scroll_timer and self._original_texts:
            # Create a timer in periodic mode (mode=-1)
            self._scroll_timer = Timer(-1)
            # Schedule the _update_scrolling method to run every 30ms
            self._scroll_timer.init(period=self._scroll_refresh, mode=Timer.PERIODIC, callback=lambda t: self._update_scrolling())
    
    def show_message(self, *lines, scrolling_lines=None):
        if scrolling_lines is None:
            scrolling_lines = []
        
        current_time = time.ticks_ms()
        
        # Process and prepare all lines
        processed_lines = []
        needs_scrolling = False
        
        for i, line in enumerate(lines):
            if i >= self.rows:
                break
                
            line_str = str(line)
            
            # If this is a scrolling line and text is longer than display
            if i in scrolling_lines and len(line_str) > self.cols:
                # Store original text if not already stored or reset position if content changed
                if i not in self._original_texts or self._original_texts[i] != line_str:
                    self._original_texts[i] = line_str
                    self._scroll_positions[i] = 0  # Reset position to beginning
                    self._scroll_timestamps[i] = current_time
                
                needs_scrolling = True
                
                # Extract the visible portion based on current scroll position
                visible_text = line_str[self._scroll_positions[i]:self._scroll_positions[i] + self.cols]
                processed_lines.append(self._pad(visible_text, self.cols))
            else:
                # Non-scrolling line, just pad normally
                if i in self._original_texts:
                    # If was scrolling but now fits or is not in scrolling_lines, reset
                    del self._original_texts[i]
                    if i in self._scroll_positions:
                        del self._scroll_positions[i]
                    if i in self._scroll_timestamps:
                        del self._scroll_timestamps[i]
                
                processed_lines.append(self._pad(line_str, self.cols))
        
        # Fill remaining lines with spaces if not enough lines provided
        while len(processed_lines) < self.rows:
            processed_lines.append(" " * self.cols)
        
        # Compare and update each line
        for row in range(self.rows):
            current_line = processed_lines[row]
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
        self._buffer = processed_lines[:self.rows]
        
        # Start or stop the scrolling timer as needed
        if needs_scrolling:
            self._start_scroll_timer()
        elif not self._original_texts:
            self._stop_scroll_timer()

    def _update_scrolling(self):
        """Update scrolling text without needing to call show_message repeatedly."""
        current_time = time.ticks_ms()
        
        # Process any scrolling lines
        for row, original_text in self._original_texts.items():
            if len(original_text) <= self.cols:
                continue  # No need to scroll if text fits
                
            # Check if it's time to update the scroll position
            time_diff = time.ticks_diff(current_time, self._scroll_timestamps.get(row, 0))
            
            # Initial pause or end pause (500ms)
            if (self._scroll_positions.get(row, 0) == 0 or 
                self._scroll_positions.get(row, 0) == len(original_text) - self.cols) and time_diff < self._scroll_wait:
                # Keep current position during pause
                pass
            elif time_diff >= self._scroll_period:  # Scroll speed (200ms per step)
                # Update scroll position
                self._scroll_timestamps[row] = current_time
                if self._scroll_positions.get(row, 0) < len(original_text) - self.cols:
                    self._scroll_positions[row] = self._scroll_positions.get(row, 0) + 1
                else:
                    # Reset to beginning after end pause
                    self._scroll_positions[row] = 0
                
                # Extract the visible portion based on current scroll position
                visible_text = original_text[self._scroll_positions[row]:self._scroll_positions[row] + self.cols]
                padded_text = self._pad(visible_text, self.cols)
                
                # Update display if text changed
                if self._buffer[row] != padded_text:
                    # Compare with buffer and only update changed characters
                    col = 0
                    while col < self.cols:
                        # Find the next character that differs
                        while col < self.cols and padded_text[col] == self._buffer[row][col]:
                            col += 1
                        
                        if col < self.cols:
                            # Found a difference, now find how many consecutive characters differ
                            start_col = col
                            while col < self.cols and padded_text[col] != self._buffer[row][col]:
                                col += 1
                            
                            # Write the chunk of changed characters
                            self.lcd.set_cursor(start_col, row)
                            self.lcd.write_text(padded_text[start_col:col])
                    
                    # Update buffer with new text
                    self._buffer[row] = padded_text
        
        # If no more scrolling lines, stop the timer
        if not self._original_texts:
            self._stop_scroll_timer()

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