import json
import time
from machine import reset
from flags import DEBUG
class ErrorManager:
    """Manages error logging with minimal flash writes."""

    ERROR_FILE = "lasterror.json"
    LOG_FILE = "log.txt"

    def __init__(self):
        self._last_error = None
        self._error_history = []  # Stores the last 3 errors and warnings
        self._error_timestamps = []  # Tracks timestamps of recent errors for rate limiting
        self._max_error_history = 10
        self._error_rate_limit = 3
        self.error_rate_limiter_reached = False

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
                self._log_to_file(f"Failed to write error log: {e}", "ERROR")

        # Log to log.txt
        self._log_to_file(f"FATAL: {error_type} - {message}", "ERROR")

    def log_error(self, message):
        """Logs a non-fatal error to log.txt and tracks it for rate limiting."""
        print(f"ERROR: {message}")
        self._log_to_file("ERROR", f"{message}")
        self._track_error_rate()
        self._add_to_history("ERROR", message)

    def log_warning(self, message):
        """Logs a warning message to the history."""
        if DEBUG>=1:
            print(f"WARNING: {message}")
        self._add_to_history("WARNING", message)

    def log_info(self, message):
        """Logs an informational message to the history."""
        if DEBUG>=2:
            print(f"INFO: {message}")
        self._add_to_history("INFO", message)

    def _log_to_file(self,level, message):
        """Logs a message to the log file."""
        try:
            with open(self.LOG_FILE, 'a') as f:
                f.write(f"{time.time()} - {level}: {message}\n")
        except Exception as e:
            print(f"Failed to write to log file: {e}")

    def _track_error_rate(self):
        """Tracks the rate of errors and sets the rate limiter flag if exceeded."""
        current_time = time.time()
        self._error_timestamps.append(current_time)

        # Remove timestamps older than 1 minute
        self._error_timestamps = [t for t in self._error_timestamps if current_time - t <= 60]

        # Check if rate limit is exceeded
        if len(self._error_timestamps) > self._error_rate_limit:  # More than 1 error per minute
            self.error_rate_limiter_reached = True
            self._log_to_file("ERROR", f"Error rate limiter triggered: {len(self._error_timestamps)} errors in the last minute")

    def reset_error_rate_limiter(self):
        """Resets the error rate limiter flag."""
        self.error_rate_limiter_reached = False
        self._error_timestamps = []

    def _add_to_history(self, level, message):
        """Adds an error or warning to the history, keeping only the last 3."""
        self._error_history.append({"level": level, "message": message, "timestamp": time.time()})
        if len(self._error_history) > self._max_error_history:
            self._error_history.pop(0)

    def get_last_error(self):
        """Returns the last fatal error if it exists."""
        try:
            with open(self.ERROR_FILE, 'r') as f:
                return json.load(f)
        except:
            return None

    def get_current_log(self):
        """Returns the current log as a string."""
        try:
            with open(self.LOG_FILE, 'r') as f:
                return f.read()
        except:
            return ""

    def get_error_warning_history(self):
        """Returns the last 3 errors and warnings."""
        return self._error_history

    def clear_error_log(self):
        """Clears the error log file."""
        try:
            with open(self.ERROR_FILE, 'w') as f:
                f.write("")
            self._last_error = None
        except Exception as e:
            self._log_to_file(f"Failed to clear error log: {e}", "ERROR")

