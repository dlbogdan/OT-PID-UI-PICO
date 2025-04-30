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
    """Handles reading/writing config using JSON format."""
    def __init__(self, filename_config:str):
        self.filename_config = filename_config
        self.config = {} # Holds the parsed config (dict of dicts with types)
        self._load_config()

    def _load_config(self):
        """Loads config from JSON file."""
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
