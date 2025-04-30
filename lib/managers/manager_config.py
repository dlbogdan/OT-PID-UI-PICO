import uos
import time
# Use standard json module
import json
from managers.manager_logger import Logger
# Import Any for type hinting
from typing import Any

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
        # Removed reload - read directly from the in-memory cache
        # self._load_config()
        
        section_dict = self.config.get(section)
        
        if isinstance(section_dict, dict) and key in section_dict:
            return section_dict[key] # Return existing value (already typed)
        else:
            # Section or key missing, use default
            logger.info(f"Config key '{section}.{key}' not found. Setting default: {repr(default)}")
            # Set the default value (with its original type) and save
            self.set(section, key, default) # set_value handles save
            return default

    def set(self, section: str, key: str, value: Any):
        """Sets the value (preserving type), saves config if changed."""
        # Ensure section exists
        if section not in self.config or not isinstance(self.config[section], dict):
            self.config[section] = {}
            
        # Only save if value actually changed
        if key not in self.config[section] or self.config[section][key] != value:
            self.config[section][key] = value # Assign value directly (preserves type)
            if not self.save_config():
                 logger.error(f"Failed to save config after setting {section}.{key}")
            # else: logger.debug(f"set_value: Value for {section}.{key} changed.")
        # else: logger.debug(f"set_value: Value for {section}.{key} unchanged.")
