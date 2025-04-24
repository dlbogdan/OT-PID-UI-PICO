# controller_menu.py
# Refactored GUI system with separation of concerns (Field + Editor pattern)
# Managed by GUIManager using UIMode components (NavigationMode, EditingMode)
# Handles HID ButtonEvents, long press, fast repeat, and mode switching.

from machine import I2C, Pin
import utime as time  # Use utime for MicroPython compatibility
from controllers.controller_HID import ButtonObserver, ButtonEventType, ButtonName, ButtonEvent
import uasyncio as asyncio # Add asyncio import
from initialization import logger


# --- End Import ---

def pad_string(text, length):
    """Pads if shorter than length, returns full text if longer."""
    text = str(text)
    return text if len(text) >= length else text + " " * (length - len(text))

# --- Menu/Field/Action Definitions ---
class Menu:
    def __init__(self, name, items):
        self.name = name
        self.items = items
        self.selected = 0

    def render(self, cols):
        # Indicate it's a menu entry
        if cols > 0: 
            return f"{self.name}"[:cols]
        else: # No cols, return full name
            return f"{self.name}"

class Action:
    def __init__(self, name, callback):
        self.name = name
        self.callback = callback

    def render(self, cols):
        # Simple action name display
        if cols > 0: 
            return f"> {self.name}"[:cols]
        else: # No cols, return full name
            return f"> {self.name}"

    def is_editable(self):
        return False # Actions are not editable

# --- Editor Base Class ---
class Editor:
    def __init__(self, field):
        self.field = field
        self.cursor_pos = -1 # Default: no cursor

    def handle(self, event):
        """Handles button events relevant to editing this field type.
           event is a ButtonEvent. Subclasses implement specific logic."""
        pass

    def render(self, cols):
        """Returns the string representation for the display."""
        return pad_string(self.field.editing_value, cols)

    def confirm(self):
        """Confirms the edit, applying changes to the field."""
        self.field.confirm()

    def cancel(self):
        """Cancels the edit, reverting changes."""
        self.field.cancel()

    def wants_cursor(self):
        """Returns True if this editor type uses a text cursor."""
        return False

# --- Editor Implementations ---
class IntEditor(Editor):
    def handle(self, event):
        if event.type != ButtonEventType.PRESSED:
            return
        try:
            current_val = int(self.field.editing_value)
        except ValueError:
            current_val = 0 # Default to 0 if parsing fails

        if event.button == ButtonName.UP:
            self.field.editing_value = str(current_val + 1)
        elif event.button == ButtonName.DOWN:
            val = max(0, current_val - 1) # Prevent going below 0
            self.field.editing_value = str(val)

class FloatEditor(Editor):
    def __init__(self, field):
        super().__init__(field)
        self.cursor_on_fraction = False # Start editing the integer part

    def handle(self, event):
        if event.type != ButtonEventType.PRESSED:
            return

        # --- Debugging Float Edit ---
        logger.debug(f"FloatEditor.handle - Start - editing_value='{self.field.editing_value}'")
        # --- End Debugging ---

        try:
            val = float(self.field.editing_value)
        except ValueError as e:
            # --- Debugging Float Edit ---
            logger.error(f"FloatEditor.handle - Failed to parse float: '{self.field.editing_value}'. Error: {e}")
            val = 0.0 # Default if parsing fails

        if event.button == ButtonName.UP:
            inc = 0.01 if self.cursor_on_fraction else 1.0
            val += inc
            self.field.editing_value = f"{val:.2f}"
            action_occurred = True
        elif event.button == ButtonName.DOWN:
            dec = 0.01 if self.cursor_on_fraction else 1.0
            val = max(0.0, val - dec) # Prevent going below 0
            self.field.editing_value = f"{val:.2f}"
            action_occurred = True
        elif event.button == ButtonName.LEFT:
            self.cursor_on_fraction = False
            action_occurred = True # Cursor state change counts as action for render
        elif event.button == ButtonName.RIGHT:
            self.cursor_on_fraction = True
            action_occurred = True # Cursor state change counts as action for render
        else:
            action_occurred = False

        # --- Debugging Float Edit ---
        if action_occurred:
            logger.debug(f"FloatEditor.handle - End - editing_value='{self.field.editing_value}'")
        # --- End Debugging ---


    def render(self, cols):
        # Highlight the part being edited (integer or fractional)
        try:
            parts = self.field.editing_value.split('.')
            if len(parts) != 2:
                 logger.warning(f"FloatEditor.render - Invalid format '{self.field.editing_value}', defaulting.")
                 parts = ['0', '00'] # Default on split error

            # --- Manual Padding for Fractional Part ---
            fractional_part = parts[1]
            if len(fractional_part) < 2:
                fractional_part += '0' * (2 - len(fractional_part))
            elif len(fractional_part) > 2:
                fractional_part = fractional_part[:2]
            parts[1] = fractional_part
            # --- End Manual Padding ---

        except Exception as e:
             logger.error(f"FloatEditor.render - Error splitting/padding: {e}, Value='{self.field.editing_value}'")
             parts = ['0', '00'] # Default on other errors

        # --- Use Brackets for Highlighting ---
        if self.cursor_on_fraction:
             highlighted_value = f"{parts[0]}.[{parts[1]}]"
        else:
             highlighted_value = f"[{parts[0]}].{parts[1]}"
        # --- End Bracket Highlighting ---

        return pad_string(highlighted_value, cols)

class BoolEditor(Editor):
    def handle(self, event):
        if event.type != ButtonEventType.PRESSED:
            return
        # Toggle on UP or DOWN press
        if event.button in (ButtonName.UP, ButtonName.DOWN):
            current_bool = self.field.editing_value.lower() == "true"
            self.field.editing_value = "True" if not current_bool else "False"

    def render(self, cols):
         # Optionally add emphasis like [True] or [False]
        return pad_string(f"[{self.field.editing_value}]", cols)


class TextEditor(Editor):
    ALLOWED_CHARS = " abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*()-_=+[]{};:'\",.<>/?\\|"

    def __init__(self, field):
        super().__init__(field)
        self.cursor_pos = len(self.field.editing_value)

    def wants_cursor(self):
        return True

    def handle(self, event):
        logger.debug(f"TextEditor.handle received: Button={event.button}, Type={event.type}, CursorPos={self.cursor_pos}, Value='{self.field.editing_value}'")

        val = list(self.field.editing_value)
        max_len = 16
        action_occurred = False

        # --- Handle LEFT/RIGHT (including Deletion for LEFT & Add 'a' for RIGHT) ---
        if event.button == ButtonName.RIGHT:
            if self.cursor_pos < len(val):
                # Move cursor right within existing text
                self.cursor_pos += 1
                action_occurred = True # Cursor moved
            elif len(val) < max_len:
                # Cursor is at end, and we have space: Add 'a' and move cursor
                logger.debug("TextEditor RIGHT - At end, adding 'a'")
                # Add 'a' which is the second character in ALLOWED_CHARS (index 1)
                val.append(self.ALLOWED_CHARS[1])
                self.cursor_pos += 1
                action_occurred = True
            # else: At end and max length reached, do nothing

        elif event.button == ButtonName.LEFT:
            original_len = len(val)
            original_pos = self.cursor_pos
            if self.cursor_pos > 0:
                # Delete character to the left of the cursor
                del val[self.cursor_pos - 1]
            # Always move cursor left (or stay at 0 if already there)
            self.cursor_pos = max(0, self.cursor_pos - 1)
            # Mark handled if length changed or cursor position changed
            if len(val) != original_len or self.cursor_pos != original_pos:
                action_occurred = True

        # --- Handle UP/DOWN Character Cycling ---
        elif event.button == ButtonName.UP or event.button == ButtonName.DOWN:
             idx_to_modify = -1 # Initialize index to invalid

             if len(val) == 0:
                  # Special case: Empty string, add first char on UP/DOWN if space available
                  if max_len > 0:
                       # Start with 'a' or '|'
                       new_char = self.ALLOWED_CHARS[1] if event.button == ButtonName.UP else self.ALLOWED_CHARS[-1]
                       val.append(new_char)
                       self.cursor_pos = 1 # Cursor is now after the new char
                       action_occurred = True
                       logger.debug(f"TextEditor UP/DOWN - Added first character '{new_char}'")
                  else:
                       logger.warning("TextEditor UP/DOWN - Cannot add char, max_len is 0?")
             else:
                  # String is not empty, determine index
                  if 0 <= self.cursor_pos < len(val):
                       # Cursor is within the string, modify character AT cursor position
                       idx_to_modify = self.cursor_pos
                       logger.debug(f"TextEditor UP/DOWN - Target index {idx_to_modify} (cursor inside)")
                  elif self.cursor_pos == len(val):
                       # Cursor is immediately after the last character, modify the LAST character
                       idx_to_modify = self.cursor_pos - 1
                       logger.debug(f"TextEditor UP/DOWN - Target index {idx_to_modify} (cursor at end)")

                  if idx_to_modify != -1:
                      # Proceed with modification if index is valid
                      original_char = val[idx_to_modify]
                      try:
                          current_char_idx = self.ALLOWED_CHARS.find(original_char)
                          if event.button == ButtonName.UP:
                              next_char_idx = (current_char_idx + 1) % len(self.ALLOWED_CHARS)
                              next_char = self.ALLOWED_CHARS[next_char_idx]
                              # print(f"DEBUG: TextEditor UP - Char='{original_char}', Idx={current_char_idx}, Next='{next_char}', NextIdx={next_char_idx}") # DEBUG
                          else: # DOWN
                              next_char_idx = (current_char_idx - 1) % len(self.ALLOWED_CHARS)
                              next_char = self.ALLOWED_CHARS[next_char_idx]
                              # print(f"DEBUG: TextEditor DOWN - Char='{original_char}', Idx={current_char_idx}, Prev='{next_char}', PrevIdx={next_char_idx}") # DEBUG

                          val[idx_to_modify] = next_char
                          if original_char != next_char:
                              logger.debug(f"TextEditor UP/DOWN - Changed index {idx_to_modify} from '{original_char}' to '{next_char}'")
                              action_occurred = True

                      except ValueError: # Handle if char not in ALLOWED_CHARS
                          val[idx_to_modify] = self.ALLOWED_CHARS[0] # Default to first allowed char (' ')
                          if original_char != self.ALLOWED_CHARS[0]:
                               action_occurred = True
                               logger.warning(f"TextEditor UP/DOWN - Char '{original_char}' not allowed, set index {idx_to_modify} to default '{self.ALLOWED_CHARS[0]}'")
                  else:
                      # This case should ideally not be reached if len(val) > 0
                      logger.warning(f"TextEditor UP/DOWN - Could not determine valid index. CursorPos={self.cursor_pos}, len={len(val)}")

        # --- Update field value only if an action actually occurred ---
        if action_occurred:
            logger.debug(f"TextEditor - Action occurred, updating value to: {''.join(val)}")
            self.field.editing_value = "".join(val)
        else:
             if event.button in (ButtonName.LEFT, ButtonName.RIGHT, ButtonName.UP, ButtonName.DOWN):
                 logger.debug("TextEditor - No effective action occurred.")

    def render(self, cols):
         return pad_string(self.field.editing_value, cols)

class IPAddressEditor(Editor):
    def __init__(self, field):
        super().__init__(field)
        self.editing_octet_index = 0 # Index of the octet being edited (0-3)

    def _parse_octets(self):
        """Safely parses the current editing value into a list of 4 integers."""
        try:
            octets = [int(part) for part in self.field.editing_value.split('.')]
            if len(octets) == 4 and all(0 <= o <= 255 for o in octets):
                return octets
        except:
            pass # Fall through on any error
        # Return default if parsing fails or validation fails
        return [0, 0, 0, 0]

    def _format_octets(self, octets):
        """Formats a list of 4 integers back into an IP string."""
        return ".".join(map(str, octets))

    def handle(self, event):
        if event.type != ButtonEventType.PRESSED:
            return

        octets = self._parse_octets()
        current_octet_val = octets[self.editing_octet_index]

        if event.button == ButtonName.UP:
            octets[self.editing_octet_index] = min(255, current_octet_val + 1)
        elif event.button == ButtonName.DOWN:
            octets[self.editing_octet_index] = max(0, current_octet_val - 1)
        elif event.button == ButtonName.LEFT:
            # Move to previous octet
            self.editing_octet_index = (self.editing_octet_index - 1) % 4
        elif event.button == ButtonName.RIGHT:
            # Move to next octet
            self.editing_octet_index = (self.editing_octet_index + 1) % 4

        # Update the editing value string
        self.field.editing_value = self._format_octets(octets)

    def render(self, cols):
        """Renders the IP address, highlighting the currently edited octet."""
        octets = self.field.editing_value.split('.')
        # Ensure we always have 4 parts for rendering, even if invalid
        while len(octets) < 4: octets.append('0')
        octets = octets[:4]

        highlighted_parts = []
        highlight_char = '\x01' # Use STX for LCD highlighting
        for i, part in enumerate(octets):
            if i == self.editing_octet_index:
                highlighted_parts.append(f"{highlight_char}{part}")
            else:
                highlighted_parts.append(part)

        return pad_string(".".join(highlighted_parts), cols)

    def confirm(self):
        # Validate before confirming
        octets = self._parse_octets()
        self.field.value = self._format_octets(octets) # Set the validated value
        self.field.editing_value = self.field.value # Sync editing value
        if self.field.callback:
            self.field.callback(self.field.value)


# --- Field Base and Concrete Implementations ---
class Field:
    """Base class for editable data fields."""
    def __init__(self, name, value, callback=None, editable=True):
        self.name = name
        self._value = value # Store initial value
        self.value = value # The confirmed value
        self.callback = callback
        self.editing_value = str(value) # String representation for editing
        self.editable = editable

    def render(self, cols):
        """Default rendering for a field in navigation mode."""
        # Indicate non-editable fields if needed (e.g., with a lock symbol)
        prefix = "" if self.editable else chr(0) # Example: Use NULL char
        return pad_string(f"{self.name}: {self.value}{prefix}", cols)

    def confirm(self):
        """Finalizes the edit. Type conversion might happen here or in editor."""
        # Basic confirmation: just set value from editing_value
        # More complex fields might override this (like IPAddressEditor does via its confirm)
        # Sync editing value AFTER potential changes in subclasses or if no override exists.
        # Note: Subclasses overriding confirm might sync editing_value themselves.
        # This line acts as a fallback or standard behavior if not overridden.
        self.editing_value = str(self.value)

        logger.info(f"Confirmed '{self.name}': {self.value}")
        if self.callback:
            self.callback(self.value)

    def cancel(self):
        """Discards changes made during editing."""
        self.editing_value = str(self.value) # Revert editing value to last confirmed value
        logger.info(f"Cancelled edit for '{self.name}'")


    def is_editable(self):
        return self.editable

    def get_editor(self):
        """Returns an appropriate Editor instance for this field."""
        # Default editor is TextEditor, subclasses override this
        logger.warning(f"Using default TextEditor for field '{self.name}'")
        return TextEditor(self)

# --- Specific Field Types ---
class IntField(Field):
    def __init__(self, name, value, callback=None):
        super().__init__(name, int(value), callback)
        self.editing_value = str(int(value)) # Ensure initial edit value is clean int string

    def get_editor(self):
        return IntEditor(self)

    def confirm(self):
        # Ensure value is stored as int
        try:
            self.value = int(self.editing_value)
        except ValueError:
            logger.error(f"confirming IntField '{self.name}': Invalid value '{self.editing_value}'. Reverting.")
            self.value = self._value # Revert to original if invalid
        self.editing_value = str(self.value)
        if self.callback:
            self.callback(self.value)


class FloatField(Field):
    def __init__(self, name, value, callback=None):
        # Handle None or invalid initial values gracefully
        initial_float = 0.0 # Default value
        if value is not None:
            try:
                initial_float = float(value)
            except (ValueError, TypeError):
                logger.warning(f"FloatField '{name}' received invalid initial value '{value}'. Defaulting to 0.0.")
                # initial_float remains 0.0
        else:
             logger.warning(f"FloatField '{name}' received None initial value. Defaulting to 0.0.")
             # initial_float remains 0.0

        # Ensure the stored value is a float
        # initial_float = float(value)
        super().__init__(name, initial_float, callback)
        # Ensure the initial editing_value string is correctly formatted
        self.editing_value = f"{initial_float:.2f}"

    def get_editor(self):
        return FloatEditor(self)

    def confirm(self):
        # Ensure value is stored as float after edit
        try:
            self.value = float(self.editing_value)
        except ValueError:
             logger.error(f"confirming FloatField '{self.name}': Invalid value '{self.editing_value}'. Reverting.")
             # Revert to the original float value if conversion fails
             self.value = float(self._value) # Use the initial stored float

        # Ensure editing_value is synced and correctly formatted after confirm/revert
        self.editing_value = f"{self.value:.2f}"
        if self.callback:
            self.callback(self.value)


class BoolField(Field):
    def __init__(self, name, value, callback=None):
        initial_bool = bool(value)
        super().__init__(name, initial_bool, callback)
        # Use 'True'/'False' strings for editing
        self.editing_value = "True" if initial_bool else "False"

    def get_editor(self):
        return BoolEditor(self)

    def confirm(self):
        # Convert 'True'/'False' string back to bool
        self.value = self.editing_value.lower() == "true"
        self.editing_value = "True" if self.value else "False" # Keep editor synced
        if self.callback:
            self.callback(self.value)


class IPAddressField(Field):
    def __init__(self, name, value="0.0.0.0", callback=None):
         # Validate and format the initial value
        validated_ip, _ = self._validate_and_parse(value)
        super().__init__(name, validated_ip, callback)
        self.editing_value = validated_ip # Start editing with validated value

    def get_editor(self):
        return IPAddressEditor(self)

    def _validate_and_parse(self, ip_str):
        """Validates an IP string and returns formatted string + parts list."""
        try:
            parts = [int(part) for part in str(ip_str).split('.')]
            if len(parts) == 4 and all(0 <= p <= 255 for p in parts):
                formatted = ".".join(map(str, parts))
                return formatted, parts
        except:
            pass # Fall through on error
        # Default invalid IP
        default_parts = [0, 0, 0, 0]
        default_formatted = "0.0.0.0"
        return default_formatted, default_parts

    def confirm(self):
        # IP editor handles validation internally via its _parse_octets
        # Here, we just ensure the editor's confirm logic ran (which sets self.value)
        # The editor's confirm method already calls the callback.
        pass # Editor's confirm method does the work


class TextField(Field): # Added specific TextField
    def __init__(self, name, value, callback=None, max_length=16, editable=True):
        super().__init__(name, str(value), callback, editable=editable)
        self.max_length = max_length # Store max length if needed

    def get_editor(self):
        # Optionally pass max_length to editor if it needs it
        editor = TextEditor(self)
        # editor.max_length = self.max_length # If editor uses it
        return editor

    def confirm(self):
        # Ensure value doesn't exceed max_length if enforced
        self.value = str(self.editing_value)[:self.max_length]
        self.editing_value = self.value # Sync editing value
        if self.callback:
            self.callback(self.value)

# --- UIMode Base Class ---
class UIMode:
    """Base class for different UI states (Navigation, Editing, Monitoring, etc.)."""
    def handle_event(self, event, manager):
        """Processes a ButtonEvent.
        Args:
            event (ButtonEvent): The button event to process.
            manager (GUIManager): The central manager instance.
        Returns:
            mixed: Typically False if not handled. Can return 'start_repeat'
                   to signal the manager to begin fast-repeating UP/DOWN actions.
                   Specific modes might return other values if needed, but
                   False and 'start_repeat' are standard.
        """
        return False # Default: event not handled

    def render(self, display):
        """Renders the UI for this mode onto the provided display object."""
        pass

    def enter(self, manager, context=None):
        """Called by the GUIManager when switching *to* this mode.
        Args:
            manager (GUIManager): The central manager instance.
            context (any): Optional data passed from the previous mode or
                           the code that initiated the mode switch.
        """
        pass

    def exit(self, manager):
        """Called by the GUIManager when switching *away* from this mode.
           Used for cleanup (e.g., stopping timers, clearing state).
        Args:
            manager (GUIManager): The central manager instance.
        """
        pass


# --- Navigation Mode ---
class NavigationMode(UIMode):
    """Handles menu browsing and item selection."""
    def __init__(self, root_menu):
        self.root_menu = root_menu
        # Menu stack for navigating back. Start with root.
        self.menu_stack = [root_menu]
        # Scrolling state is now fully managed by the DisplayController.
        # Removed: self.scroll_pos, self.scroll_speed, self.scroll_pause_ticks,
        #          self.scroll_pause_counter, self.last_scroll_time, self.scroll_interval_ms
        # Removed: self._current_display_text

    @property
    def current_menu(self):
        """Returns the currently active menu (top of the stack)."""
        return self.menu_stack[-1] if self.menu_stack else self.root_menu

    def enter(self, manager, context=None):
        logger.info("Entering Navigation Mode")
        # If context specifies a menu, try to navigate to it? Complex.
        # For now, just ensure we reset scroll on entry.
        # Removed call to self._reset_scroll()
        manager.render() # Render immediately on entering

    def exit(self, manager):
        logger.info("Exiting Navigation Mode")
        # No specific cleanup needed currently for navigation

    def render(self, display):
        menu = self.current_menu
        title = pad_string(menu.name, display.cols)

        if menu.items:
            # Ensure selection is valid
            if not (0 <= menu.selected < len(menu.items)):
                menu.selected = 0

            item = menu.items[menu.selected]
            item_text = item.render(0) # Render with more space for scrolling

            # Removed assignment to self._current_display_text
            # Optional: Add indicator for non-editable fields
            if isinstance(item, Field) and not item.is_editable():
                # Add indicator (e.g., at the end) if space allows
                if len(title) < display.cols:
                    title = title[:-1] + chr(0) # Use null char as example lock icon
        else:
            item_text = pad_string("<Empty>", display.cols)

        # Navigation mode typically doesn't show a cursor
        display.show_cursor(False)
        lines_to_show = [title, item_text] # Example for 2-row display
  
        # Assuming 'display' is the DisplayController instance
        logger.info(lines_to_show)
        display.show_message(*lines_to_show, scrolling_lines=[0, 1])

    def handle_event(self, event, manager):
        menu = self.current_menu
        if not menu.items and event.button != ButtonName.LEFT: # Allow back from empty menu
            return False

        handled = False
        if event.type == ButtonEventType.PRESSED:
            num_items = len(menu.items)
            if event.button == ButtonName.UP:
                if num_items > 0:
                    menu.selected = (menu.selected - 1 + num_items) % num_items
                    # Removed call to self._reset_scroll()
                    handled = True
            elif event.button == ButtonName.DOWN:
                 if num_items > 0:
                    menu.selected = (menu.selected + 1) % num_items
                    # Removed call to self._reset_scroll()
                    handled = True
            elif event.button == ButtonName.SELECT:
                if num_items > 0:
                    item = menu.items[menu.selected]
                    if isinstance(item, Menu):
                        # Navigate into submenu
                        self.menu_stack.append(item)
                        item.selected = 0 # Reset selection in new menu
                        # Removed call to self._reset_scroll()
                        handled = True
                    elif isinstance(item, Field) and item.is_editable():
                        # Switch to editing mode, pass field as context
                        manager.switch_mode("editing", context={'field': item})
                        # No need to set handled=True, mode switch handles redraw etc.
                        return True # Event consumed by mode switch
                    elif isinstance(item, Action):
                        # Execute the action's callback
                        if item.callback:
                            try:
                                item.callback()
                            except Exception as e:
                                # Log the error in addition to printing
                                error_message = f"Error executing action '{item.name}': {e}"
                                logger.error(error_message)
                                # Optionally show error on display?
                        handled = True
            # Note: Back (LEFT) is handled as long press below
            elif event.button == ButtonName.LEFT:
                # Go back up the menu stack OR switch to monitoring if at root
                if len(self.menu_stack) > 1:
                    self.menu_stack.pop() # Remove current menu from stack
                    # Removed call to self._reset_scroll()
                    handled = True
                elif len(self.menu_stack) == 1 and "monitoring" in manager.modes:
                    # At root menu and monitoring exists, switch to it
                    manager.switch_mode("monitoring")
                    return True # Consumed by mode switch
                # else: At root and no monitoring mode, or error, do nothing

        # Trigger re-render ONLY if the event was handled within this mode
        # (Mode switches handle their own rendering)
        if handled:
            manager.render()

        return handled

    # Removed _reset_scroll method

    # Removed _scroll_text method

# --- Monitoring Mode Components ---
class MonitorPage:
    """Base class for a single page shown in MonitoringMode."""
    def render(self, display):
        """Renders this page's content onto the display."""
        raise NotImplementedError

class Page(MonitorPage):
    """A simple monitor page defined by functions providing line content."""
    def __init__(self, line1_provider, line2_provider):
        if not callable(line1_provider) or not callable(line2_provider):
            raise TypeError("Providers must be callable (e.g., lambda functions)")
        self.line1_provider = line1_provider
        self.line2_provider = line2_provider

    def render(self, display): #todo: handle bigger displays too
        try:
            line1 = self.line1_provider()
            line2 = self.line2_provider()
            display.show_message(str(line1), str(line2))
        except Exception as e:
            logger.error(f"getting page content: {e}")
            # Try to display something informative
            try:
                display.show_message("Err:", str(e)[:display.cols])
            except:
                display.show_message("Err:", "Render failed")


# --- Monitoring Mode ---
class MonitoringMode(UIMode):
    """Handles displaying different MonitorPage objects, cyclable with UP/DOWN.
    Automatically refreshes the current page at a set interval.
    """
    def __init__(self, refresh_interval_ms=1000):
        self.pages = [] # List to store MonitorPage objects
        self.current_page_index = 0
        # Services are no longer stored here
        self.refresh_interval_ms = refresh_interval_ms
        self._refresh_task = None # Handle for the refresh task
        logger.info(f"MonitoringMode initialized (Refresh: {refresh_interval_ms}ms)")

    def add_page(self, page_object):
        """Adds a MonitorPage object to the list."""
        if isinstance(page_object, MonitorPage): # Check type
            self.pages.append(page_object)
            # Try to get a meaningful name, fallback for instances
            page_name = getattr(page_object, 'name', type(page_object).__name__)
            logger.info(f"Added monitor page: {page_name}")
        else:
            logger.error("Error: Tried to add non-MonitorPage object to MonitoringMode")

    def enter(self, manager, context=None):
        logger.info("Entering Monitoring Mode")
        # Ensure index is valid on entry, especially if pages were added dynamically
        if not self.pages:
            logger.warning("Warning: MonitoringMode has no pages.")
            self.current_page_index = -1 # Indicate no valid page
        else:
            self.current_page_index = max(0, min(self.current_page_index, len(self.pages) - 1))

        # Start the refresh task if interval is valid
        self._cancel_refresh_task() # Ensure no old task is running
        if self.refresh_interval_ms > 0:
            self._refresh_task = asyncio.create_task(self._refresh_task_coro(manager))
            logger.info("MonitoringMode: Started refresh task.")

        manager.render() # Render the current page immediately

    def exit(self, manager):
        """Called when switching away from this mode."""
        logger.info("Exiting Monitoring Mode")
        self._cancel_refresh_task()

    def render(self, display):
        display.show_cursor(False) # Monitoring never shows cursor
        if 0 <= self.current_page_index < len(self.pages):
            try:
                # Call the current page object's render method
                page_obj = self.pages[self.current_page_index]
                page_obj.render(display)
            except Exception as e:
                error_message = f"Error rendering monitor page {self.current_page_index}: {e}"
                logger.error(error_message)
                display.show_message("Monitor Error", f"Page {self.current_page_index+1} err")
        else:
            # No pages or invalid index
            display.show_message("Monitoring", "(No pages)")

    def handle_event(self, event, manager):
        if not self.pages: return False # No pages, nothing to do

        num_pages = len(self.pages)
        handled = False

        if event.type == ButtonEventType.PRESSED:
            if event.button == ButtonName.UP:
                self.current_page_index = (self.current_page_index - 1 + num_pages) % num_pages
                handled = True
            elif event.button == ButtonName.DOWN:
                self.current_page_index = (self.current_page_index + 1) % num_pages
                handled = True
            elif event.button == ButtonName.SELECT:
                # Go back to navigation mode
                manager.switch_mode("navigation")
                return True # Consumed by mode switch

        # Re-render if page changed
        if handled:
            manager.render()

        return handled

    # --- Refresh Task ---
    async def _refresh_task_coro(self, manager):
        """Coroutine that periodically triggers a re-render."""
        logger.info("MonitoringMode Refresh Task: Started.")
        try:
            while True:
                await asyncio.sleep_ms(self.refresh_interval_ms)
                logger.info("MonitoringMode Refresh Task: Tick - Rendering.")
                try:
                    # Check if we are still in monitoring mode before rendering
                    # This is a safety check, exit() should cancel the task.
                    if manager.current_mode is self:
                        manager.render()
                    else:
                        logger.info("MonitoringMode Refresh Task: Mode changed, exiting loop.")
                        break
                except Exception as e:
                    # Log error during render
                    error_message = f"Error during monitor refresh render: {e}"
                    logger.error(error_message)
                    # Continue trying to refresh
        except asyncio.CancelledError:
            logger.info("MonitoringMode Refresh Task: Cancelled.")
        except Exception as e:
            # Log general task error
            error_message = f"Error in MonitoringMode Refresh Task: {e}"
            logger.error(error_message)
        finally:
            logger.info("MonitoringMode Refresh Task: Finished.")

    def _cancel_refresh_task(self):
        """Safely cancels the refresh task if it's running."""
        if self._refresh_task and not self._refresh_task.done():
            try:
                logger.info("MonitoringMode: Cancelling refresh task.")
                self._refresh_task.cancel()
                # Allow the task to finish cancelling itself
            except Exception as e:
                logger.error(f"cancelling refresh task: {e}")
        self._refresh_task = None # Clear the handle


# --- Editing Mode ---
class EditingMode(UIMode):
    """Handles editing of a specific Field using its Editor."""
    def __init__(self):
        self.editor = None
        self.editing_field = None
        # Cursor state managed internally by render based on editor.wants_cursor()
        self._cursor_visible_state = False

    def enter(self, manager, context):
        logger.info("Entering Editing Mode")
        if context and isinstance(context.get('field'), Field):
            self.editing_field = context['field']
            # --- Use the field's existing editing_value which should be pre-formatted ---
            # No need to reset here, FloatField init/confirm handles formatting.
            # self.editing_field.editing_value = str(self.editing_field.value) # OLD
            logger.debug(f"DEBUG: EditingMode.enter - Using Field's editing_value: '{self.editing_field.editing_value}'")
            # --- End Change ---

            self.editor = self.editing_field.get_editor()
            logger.info(f"Editing field: {self.editing_field.name} with {type(self.editor).__name__}")
            manager.render() # Render editor immediately
        else:
            error_message = "Error: EditingMode entered without valid 'field' in context."
            logger.error(error_message) # Log as warning
            manager.switch_mode("navigation")

    def exit(self, manager):
        logger.info("Exiting Editing Mode")
        # Ensure cursor is turned off if it was on
        if self._cursor_visible_state:
            manager.display.show_cursor(False)
            self._cursor_visible_state = False
        # Clear references
        self.editor = None
        self.editing_field = None

    def render(self, display):
        if not self.editor or not self.editing_field:
            error_message = "EditingMode.render: Editor or field missing!"
            logger.warning(error_message) # Log as warning
            display.show_message("Edit Error", "")
            if self._cursor_visible_state: display.show_cursor(False)
            self._cursor_visible_state = False
            return

        # Title is the field name
        title = pad_string(self.editing_field.name, display.cols)
        # Value is rendered by the specific editor
        value_text = self.editor.render(display.cols)
        display.show_message(title, value_text)

        # Manage cursor based on editor type and state
        if self.editor.wants_cursor():
            # --- Adjusted Cursor Position Logic ---
            # Calculate the column where the cursor should appear ON the character being edited
            editor_cursor_pos = self.editor.cursor_pos
            current_text_len = len(self.editing_field.editing_value)

            # Default to the editor's cursor position
            effective_cursor_col = editor_cursor_pos

            # If the editor's cursor is logically *after* the last character,
            # display the cursor *over* the last character for editing.
            if editor_cursor_pos == current_text_len and current_text_len > 0:
                effective_cursor_col = editor_cursor_pos - 1

            # Ensure the display column is within valid bounds (0 to cols-1)
            final_col = max(0, min(effective_cursor_col, display.cols - 1))
            # --- End Adjusted Logic ---

            display.show_cursor_pos(True, final_col, 1) # Assuming value is on line 1 (0-indexed)
            self._cursor_visible_state = True
        else:
            # Turn off cursor if editor doesn't want it or if it was previously on
            if self._cursor_visible_state:
                display.show_cursor(False)
            self._cursor_visible_state = False


    def handle_event(self, event, manager):
        if not self.editor: return False
        logger.debug(f"EditingMode.handle_event received: Button={event.button}, Type={event.type}")

        start_repeat = False
        handled = False
        call_editor_handle = False # Flag to decide if editor's logic should run

        # --- Exit / Confirm / Cancel ---
        if event.button == ButtonName.LEFT and event.type == ButtonEventType.PRESSED_LONG:
            logger.debug("EditingMode - Matched: LONG PRESS on LEFT (Cancel)")
            self.editor.cancel()
            manager.switch_mode("navigation")
            return True # Consumed, do not call editor handle

        elif event.button == ButtonName.SELECT:
            # Confirm on PRESS or LONG_PRESS
            if event.type == ButtonEventType.PRESSED or event.type == ButtonEventType.PRESSED_LONG:
                logger.debug(f"EditingMode - Matched: {'PRESS' if event.type == ButtonEventType.PRESSED else 'LONG PRESS'} on SELECT (Confirm)")
                self.editor.confirm()
                manager.switch_mode("navigation")
                return True # Consumed, do not call editor handle

        # --- Decide if Editor Logic should Run ---
        # Run editor logic for standard presses of LEFT/RIGHT/UP/DOWN
        # Also run for LONG presses of UP/DOWN (to handle the initial action before repeat starts)
        if event.type == ButtonEventType.PRESSED and event.button in (ButtonName.LEFT, ButtonName.RIGHT, ButtonName.UP, ButtonName.DOWN):
            logger.debug("EditingMode - Condition Met: Standard PRESS on directional")
            call_editor_handle = True
            handled = True
        elif event.type == ButtonEventType.PRESSED_LONG and event.button in (ButtonName.UP, ButtonName.DOWN):
            logger.debug("EditingMode - Condition Met: LONG PRESS on UP/DOWN")
            call_editor_handle = True
            handled = True
            start_repeat = 'start_repeat' # Signal repeat ONLY on long press UP/DOWN
        # else:
        #      # Only print if it wasn't an exit/confirm action
        #      if not (event.button == ButtonName.LEFT and event.type == ButtonEventType.PRESSED_LONG) and \
        #         not (event.button == ButtonName.SELECT and event.type in (ButtonEventType.PRESSED, ButtonEventType.PRESSED_LONG)):
        #           print("DEBUG: EditingMode - Event did not match conditions to call editor handle") # DEBUG

        # --- Call Editor Handle if needed ---
        if call_editor_handle:
            logger.debug("EditingMode - Calling self.editor.handle()")
            try:
                self.editor.handle(event)
            except Exception as e:
                error_message = f"Exception during self.editor.handle(): {e}"
                logger.error(error_message)
        # else:
        #      if DEBUG >= 2: print("DEBUG: EditingMode - NOT calling self.editor.handle()") # DEBUG

        # --- Render if handled ---
        if handled:
             # print("DEBUG: EditingMode - Calling manager.render()") # DEBUG - Render might be too noisy
             manager.render()
        # else:
        #      # Only print if not handled and not an exit/confirm action
        #       if not (event.button == ButtonName.LEFT and event.type == ButtonEventType.PRESSED_LONG) and \
        #          not (event.button == ButtonName.SELECT and event.type in (ButtonEventType.PRESSED, ButtonEventType.PRESSED_LONG)):
        #            print("DEBUG: EditingMode - Event not handled in this mode.") # DEBUG

        # --- Return repeat signal or handled status ---
        # print(f"DEBUG: EditingMode - Returning: start_repeat={start_repeat}, handled={handled}") # DEBUG - Return might be too noisy
        return start_repeat if start_repeat else handled


# --- GUIManager Class ---
class GUIManager(ButtonObserver):
    """Manages different UI Modes and dispatches input events."""
    def __init__(self, display, input_device):
        self.display = display
        self.input = input_device # Expects an object providing add_observer
        self.modes = {}           # Dictionary to store registered UIMode instances
        self.current_mode_name = None
        self.current_mode = None  # The active UIMode instance

        # Fast repeat state (managed centrally)
        self._repeat_button = None # Which button is being held (UP or DOWN)
        self._repeat_task = None   # Asyncio task for repeating action
        self._repeat_interval_ms = 100 # Speed of repeat

        # Register self with the input device
        if hasattr(input_device, 'add_observer'):
             input_device.add_observer(self)
        else:
             logger.warning("Warning: Input device lacks add_observer method.")

    def add_mode(self, name, mode_instance):
        """Registers a UI mode instance with a unique name."""
        if not isinstance(mode_instance, UIMode):
             raise TypeError("mode_instance must be a subclass of UIMode")
        self.modes[name] = mode_instance
        logger.info(f"Mode '{name}' registered ({type(mode_instance).__name__})")


    def switch_mode(self, name, context=None):
        """Switches the active UI mode.
        Args:
            name (str): The name of the mode to switch to.
            context (any): Optional data to pass to the new mode's enter() method.
        """
        logger.info(f"Attempting to switch mode to: {name}")
        target_mode = self.modes.get(name)

        if not target_mode:
            error_message = f"Error: Mode '{name}' not found!"
            logger.error(error_message)
            return

        # Cancel any ongoing repeat task before switching modes
        self._cancel_repeat_task()

        # Call exit() on the current mode, if one is active
        if self.current_mode:
            try:
                self.current_mode.exit(self)
            except Exception as e:
                error_message = f"Error calling exit() on mode {self.current_mode_name}: {e}"
                logger.error(error_message)

        # Set the new mode
        self.current_mode_name = name
        self.current_mode = target_mode

        # Call enter() on the new mode
        try:
            logger.info(f"Entering mode '{name}'...")
            self.current_mode.enter(self, context)
            # Initial render should be triggered by enter() or subsequent event handling
            # self.render() # Avoid double rendering if enter() calls render()
        except Exception as e:
            error_message = f"Error calling enter() on mode {self.current_mode_name}: {e}"
            logger.error(error_message)
            self.current_mode = None
            self.current_mode_name = None


    def render(self):
        """Clears display and renders the current active mode."""
        # Clear display before rendering new content (optional, display might handle it)
        # self.display.clear()
        if self.current_mode:
            try:
                self.current_mode.render(self.display)
            except Exception as e:
                error_message = f"Error rendering mode {self.current_mode_name}: {e}"
                logger.error(error_message)
                self.display.show_message("Render Error", f"{e}")
        else:
            # Display something if no mode is active (e.g., during startup or error)
            self.display.show_message("System Ready", "(No mode active)")


    def on_button_event(self, event):
        """Callback entry point for ButtonEvents from the input device."""
        # print(f"GUIManager received event: {event} | Current repeat button: {self._repeat_button}") # More debug

        if not self.current_mode:
            logger.error("No current mode to handle event")
            return # Ignore events if no mode is active

        response = None # Store response from mode's handler

        # --- Refined Repeat Task Cancellation ---
        if self._repeat_task and not self._repeat_task.done():
            # Condition 1: The repeating button was released
            is_release_of_repeat_button = (event.button == self._repeat_button and
                                           event.type in (ButtonEventType.RELEASED, ButtonEventType.RELEASED_LONG))

            # Condition 2: A *different* button was *pressed* (not released)
            is_press_on_other_button = (event.button != self._repeat_button and
                                        event.type in (ButtonEventType.PRESSED, ButtonEventType.PRESSED_LONG))

            if is_release_of_repeat_button or is_press_on_other_button:
                logger.debug(f"Stopping repeat task for '{self._repeat_button}' due to event: Button='{event.button}', Type={event.type}")
                self._cancel_repeat_task()
                # Note: We still process the event that caused the cancellation below.

        # --- Delegate Event Handling to Current Mode ---
        try:
            response = self.current_mode.handle_event(event, self)
        except Exception as e:
             error_message = f"Error handling event in mode {self.current_mode_name}: {e}"
             logger.error(error_message)
             # Optionally show error on display or switch to error mode


        # --- Start Repeat Task if Mode Signaled ---
        # Check the response *after* handling the event
        if response == 'start_repeat':
             # Only start if no task is currently running/pending
            if self._repeat_task is None or self._repeat_task.done():
                 # Check if the event that triggered this is still valid for repeating
                 if event.button in (ButtonName.UP, ButtonName.DOWN) and event.type == ButtonEventType.PRESSED_LONG:
                     self._repeat_button = event.button
                     logger.debug(f"Manager starting repeat task for {self._repeat_button}")
                     # The mode's handle_event should have handled the *first* action already.
                     # Schedule the async task to handle subsequent repeats.
                     self._repeat_task = asyncio.create_task(self._repeat_action_task())
                 else:
                      logger.warning(f"'start_repeat' signal received for non-repeatable event: {event.button}, {event.type}")
            else:
                 logger.warning(f"'start_repeat' signal ignored, task already active for {self._repeat_button}.")

        # Rendering is handled within mode's handle_event or enter methods.


    async def _repeat_action_task(self):
        """Asynchronous task that repeatedly simulates PRESSED events for UP/DOWN."""
        if not self._repeat_button:
             logger.error("_repeat_action_task started without _repeat_button set.")
             return

        logger.debug(f"Repeat task started: Button {self._repeat_button}")
        # Store button locally in case self._repeat_button is cleared by cancellation
        repeating_button = self._repeat_button

        try:
            while True:
                # Short pause between repeats
                await asyncio.sleep_ms(self._repeat_interval_ms)

                # Crucial Check: Has the task been cancelled or state changed?
                # Check asyncio cancellation flag first.
                # Also check if we still have a current mode and the repeat button matches.
                if not self.current_mode or self._repeat_button != repeating_button:
                    # print(f"Repeat task loop break: Mode={self.current_mode_name}, Btn={self._repeat_button} (expected {repeating_button})")
                    break # Exit loop if state changed or button mismatch

                # Simulate a standard PRESSED event for the held button
                sim_event = ButtonEvent(ButtonEventType.PRESSED, repeating_button)
                # print(f"Repeat task: Handling {sim_event}") # Debug

                # Dispatch the simulated event to the current mode
                try:
                    # Mode's handle_event is responsible for rendering the change
                    self.current_mode.handle_event(sim_event, self)
                except Exception as e:
                    error_message = f"Error handling repeat event in mode {self.current_mode_name}: {e}"
                    logger.error(error_message)
                    break # Stop repeating on error

        except asyncio.CancelledError:
            logger.info(f"Repeat task cancelled for Button {repeating_button}")
            # This is expected when _cancel_repeat_task is called
        except Exception as e:
            error_message = f"Unexpected error in repeat task: {e}"
            logger.error(error_message)
        finally:
            logger.debug(f"Repeat task finished for Button {repeating_button}.")
            # Clean up state ONLY if this task instance is the one currently stored
            # (prevents race conditions if cancelled/restarted quickly)
            current_task = asyncio.current_task()
            if self._repeat_task is current_task:
                self._repeat_task = None
                self._repeat_button = None
                logger.debug("Repeat task state cleared by task itself.")

    def _cancel_repeat_task(self):
            """Safely cancels the asyncio repeat task if it's running."""
            if self._repeat_task and not self._repeat_task.done():
                try:
                    logger.info(f"Cancelling repeat task for Button {self._repeat_button}")
                    self._repeat_task.cancel()
                    # Important: Let the task's finally block clear _repeat_task and _repeat_button
                    # to avoid race conditions. Do not clear them here directly.
                except Exception as e:
                    logger.error(f"Error during repeat task cancellation: {e}")
        # else:
            # print("Cancel requested, but no repeat task active or already finished.")

# --- LogView Mode ---
class LogView(UIMode):
    """Displays text from a file with scrolling and navigation."""
    def __init__(self, file_path, display_rows, display_cols):
        self.file_path = file_path
        self.display_rows = display_rows
        self.display_cols = display_cols
        self.current_line_index = 0  # Index of the currently focused line in the file
        self.cursor_position = 0  # Position of the cursor within the visible lines
        self.buffer_start_index = 0  # Start index of the buffer in the file
        self.buffer = []  # Holds the currently loaded lines

    def _load_buffer(self):
        """Loads lines into the buffer and sets end_of_file_reached.
           EOF is considered reached if loading the buffer results in fewer
           lines than display_rows.
        """
        self.buffer = []
        self.end_of_file_reached = False # Assume not EOF initially
        lines_loaded = 0
        try:
            with open(self.file_path, 'r') as f:
                line_counter = 0
                for line in f:
                    # Skip lines before buffer start
                    if line_counter < self.buffer_start_index:
                        line_counter += 1
                        continue

                    # Load lines into buffer (up to display_rows)
                    if lines_loaded < self.display_rows:
                        self.buffer.append(line.strip()) # strip() might be important
                        lines_loaded += 1
                    else:
                        # Buffer is full, stop reading for this pass
                        break

                    line_counter += 1

            # Determine EOF based on whether we could fill the buffer
            if lines_loaded < self.display_rows:
                self.end_of_file_reached = True
            # else: Buffer is full, so we are definitely not at EOF yet.

        except Exception as e:
            error_message = f"Error loading log file buffer: {e}"
            logger.error(error_message)
            self.buffer = [] # Clear buffer on error
            self.end_of_file_reached = True # Treat error as EOF

    def enter(self, manager, context=None):
        logger.info("Entering LogView Mode")
        self.current_line_index = 0
        self.cursor_position = 0
        self.buffer_start_index = 0
        self._load_buffer()
        # Ensure cursor_position is valid after initial load
        self.cursor_position = min(self.cursor_position, max(0, len(self.buffer) - 1))
        manager.render()

    def exit(self, manager):
        logger.info("Exiting LogView Mode")
        self.buffer = []

    def render(self, display):
        display.show_cursor(False)
        lines_to_display = []
        scroll_these = [] # List to hold indices of lines needing scroll

        # Process lines that are actually in the buffer
        for i in range(len(self.buffer)):
            line = self.buffer[i]
            prefix = ">" if i == self.cursor_position else " "
            # Construct the full potential line content *before* padding/truncation
            full_line_content = f"{prefix}{line}"

            # Check if this line is focused AND needs scrolling
            if i == self.cursor_position and len(full_line_content) > self.display_cols:
                scroll_these.append(i) # Mark this line index for scrolling

            # Pad/truncate the line content for the list we build
            # The display controller will handle the actual scrolling based on the full content
            # But we still need to pass correctly formatted lines initially.
            line_with_prefix = pad_string(full_line_content, self.display_cols)
            lines_to_display.append(line_with_prefix)

        # Pad the list with blank lines if buffer is shorter than display height
        while len(lines_to_display) < self.display_rows:
            lines_to_display.append(" " * self.display_cols)

        # Pass the full list AND the list of lines to scroll
        display.show_message(*lines_to_display, scrolling_lines=scroll_these)

    def handle_event(self, event, manager):
        action_taken = False # Flag to track if state changed
        if event.type == ButtonEventType.PRESSED:
            if event.button == ButtonName.UP:
                if self.cursor_position > 0:
                    self.cursor_position -= 1
                    action_taken = True
                elif self.buffer_start_index > 0:
                    # Scroll up
                    self.buffer_start_index -= 1
                    self._load_buffer()
                    # Cursor position stays at the top after scrolling up
                    self.cursor_position = 0
                    action_taken = True
                # else: At top of file, do nothing

            elif event.button == ButtonName.DOWN:
                # Can cursor move down within the current buffer?
                if self.cursor_position < len(self.buffer) - 1:
                    self.cursor_position += 1
                    action_taken = True
                # Is cursor at the bottom of buffer, but file *might* continue?
                elif not self.end_of_file_reached:
                    # Attempt to scroll buffer down
                    original_start_index = self.buffer_start_index
                    self.buffer_start_index += 1
                    self._load_buffer()

                    # Check if the scroll actually loaded a valid next view
                    if len(self.buffer) > 0:
                        # Scroll successful, keep cursor at the bottom of the new (potentially shorter) buffer view
                        self.cursor_position = len(self.buffer) - 1
                        action_taken = True
                    else:
                        # Scroll failed (hit EOF), revert state
                        self.buffer_start_index = original_start_index
                        self._load_buffer() # Reload previous view
                        # Cursor stays where it was (last line of previous view)
                        self.cursor_position = len(self.buffer) - 1
                        # No action_taken = True, as state is unchanged
                # else: Cursor is at bottom of buffer AND end_of_file_reached is True. Do nothing.

            elif event.button == ButtonName.LEFT:
                # Exit LogView and return to the menu
                manager.switch_mode("navigation")
                return True # Event consumed by mode switch

        # Render only if an action was taken that changed the state
        if action_taken:
            manager.render()

        return action_taken # Return True if handled (state changed), False otherwise