import uos
import time
# Use standard json module
import json
from managers.manager_logger import Logger
# Import Any for type hinting
from typing import Any, Callable, Dict, List

logger = Logger()

# --- Configuration Management ---
class ConfigManager:
    """Handles reading/writing config using JSON format (Singleton)."""
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, filename_config:str):
        if self._initialized:
            return # Prevent re-initialization
        logger.debug(f"Initializing ConfigManager with filename: {filename_config}")
        self.filename_config = filename_config
        self.config = {} # Holds the parsed config (dict of dicts with types)
        # Observer pattern: Store listeners keyed by "section.key"
        self._listeners: Dict[str, List[Callable[[Any], None]]] = {}
        self._load_config()
        self._initialized = True # Mark as initialized

    def _load_config(self):
        """Loads config from JSON file."""
        # Check if filename_config is set (can happen if __new__ returns existing instance before __init__ runs)
        if not hasattr(self, 'filename_config') or not self.filename_config:
             # Try to get it from the instance if it was already initialized
            if ConfigManager._instance and hasattr(ConfigManager._instance, 'filename_config'):
                self.filename_config = ConfigManager._instance.filename_config
            else:
                logger.error("Cannot load config: filename_config not set.")
                self.config = {}
                return
                
        try:
            with open(self.filename_config, 'r') as f:
                loaded_data = json.load(f)
                if isinstance(loaded_data, dict):
                    self.config = loaded_data
                    logger.info(f"Loaded config from {self.filename_config}")
                else:
                    logger.error(f"Invalid config format in {self.filename_config} (not a dictionary). Using empty config.")
                    self.config = {}
        except (OSError, ValueError) as e:
            # OSError -> File not found or read error
            # ValueError -> Invalid JSON
            logger.warning(f"Could not load config from {self.filename_config} ({e}). Using empty config. Defaults will be created.")
            self.config = {}
        except Exception as e:
             logger.error(f"Unexpected error loading config {self.filename_config}: {e}")
             self.config = {}

    def save_config(self):
        """Save the current configuration to the JSON config file."""
        try:
            with open(self.filename_config, 'w') as f:
                # Use positional arguments only for MicroPython compatibility
                json.dump(self.config, f) # No keyword args
            logger.info(f"Config successfully saved to {self.filename_config}") 
            return True
        except Exception as e:
            logger.error(f"Error saving config to {self.filename_config}: {e}")
            return False

    def get(self, section: str, key: str, default: Any = None) -> Any:
        """Gets value, setting default (and saving) if missing. Preserves type from load/default."""    
        section_dict = self.config.get(section)
        
        if isinstance(section_dict, dict) and key in section_dict:
            return section_dict[key] # Return existing value (already typed)
        else:
            # Section or key missing, use default
            logger.info(f"Config key '{section}.{key}' not found. Setting default: {repr(default)}")
            # Set the default value (with its original type) and save
            self.set(section, key, default) # set_value handles save and notification
            return default

    def set(self, section: str, key: str, value: Any):
        """Sets the value (preserving type), saves config, and notifies listeners if changed."""
        # Ensure section exists
        if section not in self.config or not isinstance(self.config[section], dict):
            self.config[section] = {}
            
        # Check if value actually changed
        current_value = self.config.get(section, {}).get(key, None)
        value_changed = (key not in self.config.get(section, {})) or (current_value != value)

        if value_changed:
            self.config[section][key] = value # Assign value directly (preserves type)
            logger.debug(f"Config set: {section}.{key} = {value}")
            
            # Attempt to save the configuration
            if not self.save_config():
                 logger.error(f"Failed to save config after setting {section}.{key}")
                 # Decide if you want to proceed with notification even if save failed
                 # For now, we proceed.
            
            # Notify listeners
            self._notify_listeners(section, key, value)

        # else: logger.debug(f"set_value: Value for {section}.{key} unchanged.")

    def _notify_listeners(self, section: str, key: str, new_value: Any):
        """Notifies registered listeners about a configuration change."""
        key_path = f"{section}.{key}"
        if key_path in self._listeners:
            # logger.debug(f"Notifying listeners for {key_path}")
            for callback in self._listeners[key_path]:
                try:
                    callback(new_value)
                except Exception as e:
                    logger.error(f"Error calling listener for {key_path}: {e}")

    def subscribe(self, key_path: str, callback: Callable[[Any], None]):
        """Registers a callback function to be notified of changes to a specific config key.

        Args:
            key_path (str): The configuration key path (e.g., "SECTION.KEY").
            callback (Callable[[Any], None]): The function to call when the value changes.
                                                It will receive the new value as an argument.
        """
        if key_path not in self._listeners:
            self._listeners[key_path] = []
        if callback not in self._listeners[key_path]:
            self._listeners[key_path].append(callback)
            # logger.debug(f"Subscribed listener to {key_path}")
        # else: logger.debug(f"Listener already subscribed to {key_path}")

    def unsubscribe(self, key_path: str, callback: Callable[[Any], None]):
        """Unregisters a callback function for a specific config key.

        Args:
            key_path (str): The configuration key path (e.g., "SECTION.KEY").
            callback (Callable[[Any], None]): The callback function to remove.
        """
        if key_path in self._listeners and callback in self._listeners[key_path]:
            self._listeners[key_path].remove(callback)
            # If no listeners remain for this key, remove the key entry
            if not self._listeners[key_path]:
                del self._listeners[key_path]
            # logger.debug(f"Unsubscribed listener from {key_path}")
        # else: logger.debug(f"Listener not found for unsubscribe on {key_path}")
