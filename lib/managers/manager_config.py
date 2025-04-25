import uos
import time
from machine import reset
from platform_spec import DEFAULT_FACTORY_CONFIG
from managers.manager_logger import Logger

logger = Logger()

# --- Configuration Management ---
# class ConfigManager: ... (NO CHANGES NEEDED) ...
class ConfigManager:
    """Handles reading and writing values in a simple .ini-style config file."""
    def __init__(self, filename_config:str, filename_factory:str):
        self.filename_config = filename_config
        self.filename_factory = filename_factory
        self.config = {}
        self._load_config()

    def _load_config(self):
        try:
            with open(self.filename_config, 'r') as f:
                current_section = None
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if line.startswith('[') and line.endswith(']'):
                        current_section = line[1:-1]
                        self.config[current_section] = {}
                    elif current_section and '=' in line:
                        key, value = line.split('=', 1)
                        self.config[current_section][key.strip()] = value.strip()
        except:
            # If file doesn't exist or is corrupted, start with empty config
            self.config = {}

    def get_value(self, section, key, default=None):
        """Retrieve the value associated with a key. If key or section is missing,
           set it to the default value, save the config, and return the default."""
        section_exists = section in self.config
        key_exists = section_exists and key in self.config[section]

        if key_exists:
            return self.config[section][key] # Return existing value
        else:
            # Key (or section) does not exist
            logger.info(f"Config key '{section}.{key}' not found. Setting default: '{default}'")
            self.set_value(section, key, default) # Creates section if needed, sets value
            self.save_config() # Save the newly added default to the file
            return default # Return the default value

    def set_value(self, section, key, value):
        """Set the value of a key in a specific section. Creates section/key if needed."""
        if section not in self.config:
            self.config[section] = {}
        self.config[section][key] = str(value)

    def save_config(self):
        """Save the current configuration to the config file."""
        success = False
        try:
            with open(self.filename_config, 'w') as f:
                for section, items in self.config.items():
                    f.write(f'[{section}]\n')
                    for key, value in items.items():
                        f.write(f'{key}={value}\n')
                    f.write('\n')
            success = True
            # Add specific confirmation log
            logger.info(f"Config successfully saved to {self.filename_config}") 
            return True
        except Exception as e:
            logger.error(f"Error saving config to {self.filename_config}: {e}")
            return False
        # finally:
        #     logger.debug(f"save_config finished. Success: {success}") # Optional debug

    
# --- Factory Reset Function ---
def factory_reset(display, led, config_manager, hm_service):
    """Performs a factory reset: deletes cache, restores config, reboots."""
    factory_config_file = config_manager.filename_factory
    config_file = config_manager.filename_config # Get current config filename
    cache_file = "hm_device_cache.json" # Assuming this is the name used in HomematicDataService

    logger.info("--- Factory Reset Initiated ---")
    if display: display.show_message("Factory Reset", "Working...")
    if led: led.direct_send_color("blue") # Indicate working state

    # 1. Delete Homematic Device Cache
    try:
        uos.remove(cache_file)
        logger.info(f"Deleted cache file: {cache_file}")
    except OSError as e:
        if e.args[0] == 2: # errno.ENOENT (File not found)
             logger.warning(f"Cache file not found (already deleted?): {cache_file}")
        else:
             logger.error(f"Error deleting cache file {cache_file}: {e}")
             if display: display.show_message("Reset Error", "Cache delete fail")
             time.sleep(3)
             # Decide if you want to proceed or stop on cache deletion failure
             # return # Uncomment to stop if cache deletion fails critically

    # 2. Ensure config_factory.txt exists, create if not
    factory_exists = False
    try:
        # Check existence by trying to get stats
        uos.stat(factory_config_file)
        factory_exists = True
        logger.info(f"Factory config file found: {factory_config_file}")
    except OSError:
        # File doesn't exist, create it from defaults
        logger.warning(f"Factory config file '{factory_config_file}' not found. Creating from defaults...")
        try:
            with open(factory_config_file, 'w') as f:
                for section, items in DEFAULT_FACTORY_CONFIG.items():
                    f.write(f'[{section}]\n')
                    for key, value in items.items():
                        f.write(f'{key}={value}\n')
                    f.write('\n')
            factory_exists = True
            logger.info("Created default factory config file.")
        except Exception as e_create:
            logger.error(f"FATAL: Could not create factory config file '{factory_config_file}': {e_create}")
            if display: display.show_message("Reset Error", "Factory create")
            time.sleep(3)
            return # Stop if we can't create the factory defaults

    # 3. Copy config_factory.txt to config.txt (if factory file exists)
    if factory_exists:
        try:
            # Simple buffered copy
            with open(factory_config_file, 'r') as f_source, open(config_file, 'w') as f_dest:
                while True:
                    chunk = f_source.read(128) # Read in chunks
                    if not chunk:
                        break
                    f_dest.write(chunk)
            logger.info(f"Copied '{factory_config_file}' to '{config_file}'")

            # Optional: Reload config in ConfigManager if needed immediately,
            # but rebooting makes this less critical.
            # config_manager._load_config()

            # 4. Final steps before reboot
            logger.info("Factory reset complete. Rebooting in 5 seconds...")
            if display: display.show_message("Factory Reset", "OK. Rebooting...")
            if led: led.direct_send_color("green") # Indicate success briefly
            time.sleep(5)
            reset() # Reboot the device

        except Exception as e_copy:
            logger.error(f"FATAL: Error copying factory config: {e_copy}")
            if display: display.show_message("Reset Error", "Config copy fail")
            if led: led.direct_send_color("red")
            time.sleep(3)
            # Stop - critical failure
            return
    else:
        # This case should ideally not be reached due to the creation logic above
        logger.error("FATAL: Factory config file could not be accessed.")
        if display: display.show_message("Reset Error", "Factory access")
        if led: led.direct_send_color("red")
        time.sleep(3)
        # Stop - critical failure
        return
