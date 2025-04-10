# button_controller.py - Handles button input via any Pin-compatible interface.
import utime

class ButtonEventType:
    PRESSED = 0
    RELEASED = 1
    PRESSED_LONG = 2
    RELEASED_LONG = 3

class ButtonName:
    LEFT = "left"
    UP = "up"
    DOWN = "down"
    RIGHT = "right"
    SELECT = "select"

class ButtonEvent:
    def __init__(self, event_type, button):
        self.type = event_type
        self.button = button

class ButtonObserver:
    """Interface for button event observers."""
    def on_button_event(self, event):
        """Called when a button event occurs."""
        pass

class HIDController:
    # State Constants
    IDLE = 0
    PRESSED = 1
    LONG_PRESSED = 2

    def __init__(self, button_left_pin, button_up_pin, button_down_pin, button_right_pin, button_select_pin):
        """Initialize with Pin-compatible objects for each button."""
        self.buttons = {
            ButtonName.LEFT: button_left_pin,
            ButtonName.UP: button_up_pin,
            ButtonName.DOWN: button_down_pin,
            ButtonName.RIGHT: button_right_pin,
            ButtonName.SELECT: button_select_pin
        }
        
        # Initialize state variables
        self.last_event = None
        self.state = self.IDLE
        self.long_press_threshold = 1000  # Long press threshold for all buttons
        self.last_press_time = 0
        self.press_start_time = 0
        self.debounce_delay = 50
        self.active_button = None
        self.long_press_detected = False
        
        # Observer pattern
        self.observers = []

    def add_observer(self, observer):
        """Add an observer to receive button events."""
        if observer not in self.observers:
            self.observers.append(observer)

    def remove_observer(self, observer):
        """Remove an observer from receiving button events."""
        if observer in self.observers:
            self.observers.remove(observer)

    def _notify_observers(self, event):
        """Notify all observers of a button event."""
        for observer in self.observers:
            observer.on_button_event(event)

    def get_event(self):
        """Get button events as ButtonEvent objects and notify observers."""
        current_time = utime.ticks_ms()

        # 1. Read Buttons (Debounced)
        pressed = None
        for button_name, pin in self.buttons.items():
            if not pin.value():  # Button pressed (active low)
                pressed = button_name
                break

        # Debounce Logic
        if pressed != self.active_button:
            if utime.ticks_diff(current_time, self.last_press_time) > self.debounce_delay:
                self.active_button = pressed
                self.last_press_time = current_time
                
                if pressed:
                    # Button pressed
                    self.press_start_time = current_time
                    self.state = self.PRESSED
                    self.long_press_detected = False
                    event = ButtonEvent(ButtonEventType.PRESSED, pressed)
                    self.last_event = event
                    self._notify_observers(event)
                    return event
                else:
                    # Button released
                    if self.last_event is not None:
                        if self.long_press_detected:
                            event = ButtonEvent(ButtonEventType.RELEASED_LONG, self.last_event.button)
                        else:
                            event = ButtonEvent(ButtonEventType.RELEASED, self.last_event.button)
                        self.reset_state()
                        self._notify_observers(event)
                        return event
                    self.reset_state()
                    return None

        # 2. Handle long press
        if self.active_button and self.state == self.PRESSED:
            press_duration = utime.ticks_diff(current_time, self.press_start_time)
            
            if press_duration >= self.long_press_threshold and not self.long_press_detected:
                self.long_press_detected = True
                self.state = self.LONG_PRESSED
                event = ButtonEvent(ButtonEventType.PRESSED_LONG, self.active_button)
                self.last_event = event
                self._notify_observers(event)
                return event

        # No valid event to return
        return None

    def reset_state(self):
        """Reset the state machine to IDLE."""
        self.state = self.IDLE
        self.active_button = None
        self.last_event = None
        self.press_start_time = 0
        self.long_press_detected = False
