import uos
import time
# Use standard json module
import json
from machine import reset
from platform_spec import DEFAULT_FACTORY_CONFIG
from managers.manager_logger import Logger
# Import Any for type hinting
from typing import Any

logger = Logger()

# --- Configuration Management ---
class ConfigManager:
    """Handles reading/writing config using JSON format."""
    def __init__(self, filename_config:str, filename_factory:str):
        self.filename_config = filename_config
        self.filename_factory = filename_factory
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
                # Add type: ignore for indent issue
                json.dump(self.config, f, indent=4) # type: ignore
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
            self.set_value(section, key, default) # set_value handles save
            return default

    def set_value(self, section: str, key: str, value: Any):
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

# --- Factory Reset Function ---
def factory_reset(display, led, config_manager, hm_service):
    """Performs a factory reset: deletes cache, restores config from defaults (JSON), reboots."""
    factory_config_file = config_manager.filename_factory
    config_file = config_manager.filename_config
    cache_file = "hm_device_cache.json" 

    logger.info("--- Factory Reset Initiated ---")
    if display: display.show_message("Factory Reset", "Working...")
    if led: led.direct_send_color("blue")

    # 1. Delete Homematic Device Cache
    try:
        uos.remove(cache_file)
        logger.info(f"Deleted cache file: {cache_file}")
    except OSError as e:
        if e.args[0] == 2: # errno.ENOENT
             logger.warning(f"Cache file not found (already deleted?): {cache_file}")
        else:
             logger.error(f"Error deleting cache file {cache_file}: {e}")
             if display: display.show_message("Reset Error", "Cache delete fail")
             time.sleep(3)
             # Continue even if cache delete fails?

    # 2. Ensure factory defaults are written to config_factory.json (if it doesn't exist)
    #    We'll always write the current defaults to the factory file, then copy.
    logger.info(f"Writing current factory defaults to {factory_config_file}...")
    try:
        with open(factory_config_file, 'w') as f_factory:
            # Add type: ignore for indent issue
            json.dump(DEFAULT_FACTORY_CONFIG, f_factory, indent=4) # type: ignore
        logger.info(f"Successfully wrote factory defaults to {factory_config_file}")
    except Exception as e_write_factory:
        logger.error(f"FATAL: Could not write factory config {factory_config_file}: {e_write_factory}")
        if display: display.show_message("Reset Error", "Factory write")
        time.sleep(3)
        return # Stop

    # 3. Copy config_factory.json to config.json
    logger.info(f"Copying {factory_config_file} to {config_file}...")
    try:
        # Simple buffered copy (might not be most efficient for large files, but fine here)
        with open(factory_config_file, 'r') as f_source, open(config_file, 'w') as f_dest:
            while True:
                chunk = f_source.read(128) 
                if not chunk:
                    break
                f_dest.write(chunk)
        logger.info(f"Successfully copied factory config to {config_file}")

        # 4. Final steps before reboot
        logger.info("Factory reset complete. Rebooting in 5 seconds...")
        if display: display.show_message("Factory Reset", "OK. Rebooting...")
        if led: led.direct_send_color("green")
        time.sleep(5)
        reset() 

    except Exception as e_copy:
        logger.error(f"FATAL: Error copying factory config: {e_copy}")
        if display: display.show_message("Reset Error", "Config copy fail")
        if led: led.direct_send_color("red")
        time.sleep(3)
        return
