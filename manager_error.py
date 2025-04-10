import json
import time
from machine import reset

class ErrorManager:
    """Manages error logging with minimal flash writes."""
    
    ERROR_FILE = "lasterror.json"
    
    def __init__(self):
        self._last_error = None
    
    def log_fatal_error(self, error_type, message, traceback=None):
        """Logs a fatal error to flash. Only writes if different from last error."""
        new_error = {
            "timestamp": time.time(),
            "type": error_type,
            "message": message,
            "traceback": traceback
        }
        
        # Only write if error is different from last one
        if self._last_error != new_error:
            try:
                with open(self.ERROR_FILE, 'w') as f:
                    json.dump(new_error, f)
                self._last_error = new_error
            except Exception as e:
                print(f"Failed to write error log: {e}")
    
    def get_last_error(self):
        """Returns the last fatal error if it exists."""
        try:
            with open(self.ERROR_FILE, 'r') as f:
                return json.load(f)
        except:
            return None
    
    def clear_error_log(self):
        """Clears the error log file."""
        try:
            with open(self.ERROR_FILE, 'w') as f:
                f.write("")
            self._last_error = None
        except Exception as e:
            print(f"Failed to clear error log: {e}")
    
