# # Hardware configuration constants
# I2C_ID = 1
# I2C_SDA_PIN = 14
# I2C_SCL_PIN = 15
# MCP_ADDRESS = 0x20

# #OPENTHERM UART configuration
# OT_UART_ID = 0
# OT_UART_TX_PIN = 16
# OT_UART_RX_PIN = 17
# OT_UART_BAUDRATE = 9600

# # RGB LED pin configuration
# RGBLED_RED_PIN = 6
# RGBLED_GREEN_PIN = 8
# RGBLED_BLUE_PIN = 7

# # Button pin configuration
# BUTTON_LEFT_PIN = 4
# BUTTON_UP_PIN = 3
# BUTTON_DOWN_PIN = 2
# BUTTON_RIGHT_PIN = 1
# BUTTON_SELECT_PIN = 0

# # LCD pin configuration
# LCD_RW_PIN = 14
# LCD_RS_PIN = 15
# LCD_EN_PIN = 13
# LCD_D4_PIN = 12
# LCD_D5_PIN = 11
# LCD_D6_PIN = 10
# LCD_D7_PIN = 9

# # LCD dimensions
# LCD_COLS = 16
# LCD_ROWS = 2


# LCD custom character definitions
DYNAMIC_CUSTOM_CHARS = [
    # Char 0: Wifi nok, Valve nok, Boiler nok
    [0x19, 0x13, 0x00, 0x19, 0x13, 0x00, 0x19, 0x13],
    # Char 1: Wifi ok, Valve nok, Boiler nok
    [0x1F, 0x1F, 0x00, 0x19, 0x13, 0x00, 0x19, 0x13],
    # Char 2: Wifi nok, Valve ok, Boiler nok
    [0x19, 0x13, 0x00, 0x1F, 0x1F, 0x00, 0x19, 0x13],
    # Char 3: Wifi nok, Valve nok, Boiler ok
    [0x19, 0x13, 0x00, 0x19, 0x13, 0x00, 0x1F, 0x1F],
    # Char 4: Wifi ok, Valve nok, Boiler ok
    [0x1F, 0x1F, 0x00, 0x19, 0x13, 0x00, 0x1F, 0x1F],
    # Char 5: Wifi nok, Valve ok, Boiler ok
    [0x19, 0x13, 0x00, 0x1F, 0x1F, 0x00, 0x1F, 0x1F],
    # Char 6: Wifi ok, Valve ok, Boiler ok
    [0x1F, 0x1F, 0x00, 0x1F, 0x1F, 0x00, 0x1F, 0x1F],
]

CUSTOM_CHARS = [
    # Char 0: Lock
    [0x0E, 0x11, 0x11, 0x1F, 0x1F, 0x1B, 0x1B, 0x1F],
    # Char 1: Right Arrow '>'
    [0x08, 0x0C, 0x0E, 0x0F, 0x0E, 0x0C, 0x08, 0x00],
    # Char 2: (Empty placeholder)
    [0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
    # Char 3: Boiler disconnected
    [0x00, 0x00, 0x1F, 0x00, 0x00, 0x1F, 0x00, 0x00],
    # Slot 4 — WiFi symbol (antenna)
    [0x0E, 0x11, 0x04, 0x0A, 0x00, 0x04, 0x04, 0x00],
    # Slot 5 — Valve OK
    [0x0E, 0x0E, 0x04, 0x0A, 0x0B, 0x0A, 0x04, 0x04],
    # Slot 6 — Valve Disconnected (striked)
    [0x00, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x00, 0x00],
    # Slot 7 — Boiler Connected
    [0x04, 0x08, 0x1F, 0x00, 0x00, 0x1F, 0x01, 0x02]
]


# Default CCU3 device types
DEFAULT_CCU3_VALVE_DEVTYPE = "HmIP-eTRV"
DEFAULT_CCU3_WEATHER_DEVTYPE = "HmIP-SWO"

# Default PID timing
DEFAULT_PID_UPDATE_INTERVAL_SEC = 30

# OpenTherm (OT) default configuration
DEFAULT_OT_MAX_HEATING_SETPOINT = 72.0
DEFAULT_OT_MANUAL_HEATING_SETPOINT = 55.0
DEFAULT_OT_DHW_SETPOINT = 50.0
DEFAULT_OT_ENABLE_CONTROLLER = False
DEFAULT_OT_ENABLE_HEATING = False
DEFAULT_OT_ENABLE_DHW = True
DEFAULT_OT_ENFORCE_DHW_SETPOINT = False
DEFAULT_OT_DEFAULT_OFF_SETPOINT = 20.0  # Default control setpoint when heating is off
DEFAULT_OT_SETPOINT_TOLERANCE = 0.1  # Tolerance for setpoint comparisons

# Auto Heating (AUTOH) default configuration
DEFAULT_AUTOH_ENABLE = True
DEFAULT_AUTOH_OFF_TEMP = 19.0
DEFAULT_AUTOH_OFF_VALVE_LEVEL = 5.0
DEFAULT_AUTOH_ON_TEMP = 15.0
DEFAULT_AUTOH_ON_VALVE_LEVEL = 12.0

# PID Controller default configuration
DEFAULT_PID_KP = 0.5
DEFAULT_PID_KI = 0.0005
DEFAULT_PID_KD = 0.02
DEFAULT_PID_SETPOINT = 10.0
DEFAULT_PID_MIN_HEATING_SETPOINT = 35.0
DEFAULT_PID_VALVE_MIN = 1.0
DEFAULT_PID_VALVE_MAX = 100.0
DEFAULT_PID_FF_WIND_COEFF = 0.1
DEFAULT_PID_FF_TEMP_COEFF = 1.1
DEFAULT_PID_FF_SUN_COEFF = 0.0001
DEFAULT_PID_FF_WIND_CHILL_COEFF = 0.008
DEFAULT_PID_BASE_TEMP_REF_OUTSIDE = 10.0
DEFAULT_PID_BASE_TEMP_BOILER = 41.0
DEFAULT_PID_OUTPUT_DEADBAND = 0.5
DEFAULT_PID_INTEGRAL_ACCUMULATION_RANGE = 5.0

CONFIG_FILENAME = "config.json"

def get_factory_config():
    """Returns a new dictionary with factory default configuration."""
    return {
        "DEVICE": {
            "DEBUG": 1,
        },
        "HARDWARE": {
            "I2C": {
                "ID": 1,
                "SDA_PIN": 14,
                "SCL_PIN": 15,
            },
            "MCP": {
                "ADDRESS": 0x20,
            },
            "UART": {
                "ID": 0,
                "TX_PIN": 16,
                "RX_PIN": 17,
                "BAUDRATE": 9600,
            },
            "RGBLED": {
                "RED_PIN": 6,
                "GREEN_PIN": 8,
                "BLUE_PIN": 7,
                "MCPPIN": True,
            },
            "BUTTONS": {
                "LEFT_PIN": 4,
                "UP_PIN": 3,
                "DOWN_PIN": 2,
                "RIGHT_PIN": 1,
                "SELECT_PIN": 0,
                "MCPPIN": True,
            },
            "LCD": {
                "RW_PIN": 14,
                "RS_PIN": 15,
                "EN_PIN": 13,
                "D4_PIN": 12,
                "D5_PIN": 11,
                "D6_PIN": 10,
                "D7_PIN": 9,
                "COLS": 16,
                "ROWS": 2,
                "MCPPIN": True,
            },
        },
        "WIFI": {
            "SSID": "ssid",
            "PASS": "pass",
            "RESET_IMMUNE": True,
        },
        "CCU3": {
            "IP": "0.0.0.0",
            "USER": "user",
            "PASS": "pass",
            "VALVE_DEVTYPE": DEFAULT_CCU3_VALVE_DEVTYPE,
            "WEATHER_DEVTYPE": DEFAULT_CCU3_WEATHER_DEVTYPE,
            "RESET_IMMUNE": True,
        },
        "OT": {
            "MAX_HEATING_SETPOINT": DEFAULT_OT_MAX_HEATING_SETPOINT,
            "MANUAL_HEATING_SETPOINT": DEFAULT_OT_MANUAL_HEATING_SETPOINT,
            "DHW_SETPOINT": DEFAULT_OT_DHW_SETPOINT,
            "ENABLE_CONTROLLER": DEFAULT_OT_ENABLE_CONTROLLER,
            "ENABLE_HEATING": DEFAULT_OT_ENABLE_HEATING,
            "ENABLE_DHW": DEFAULT_OT_ENABLE_DHW,
            "ENFORCE_DHW_SETPOINT": DEFAULT_OT_ENFORCE_DHW_SETPOINT,
        },
        "AUTOH": {
            "ENABLE": DEFAULT_AUTOH_ENABLE,
            "OFF_TEMP": DEFAULT_AUTOH_OFF_TEMP,
            "OFF_VALVE_LEVEL": DEFAULT_AUTOH_OFF_VALVE_LEVEL,
            "ON_TEMP": DEFAULT_AUTOH_ON_TEMP,
            "ON_VALVE_LEVEL": DEFAULT_AUTOH_ON_VALVE_LEVEL,
        },
        "PID": {
            "KP": DEFAULT_PID_KP,
            "KI": DEFAULT_PID_KI,
            "KD": DEFAULT_PID_KD,
            "SETPOINT": DEFAULT_PID_SETPOINT,
            "UPDATE_INTERVAL_SEC": DEFAULT_PID_UPDATE_INTERVAL_SEC,
            "VALVE_MIN": DEFAULT_PID_VALVE_MIN,
            "VALVE_MAX": DEFAULT_PID_VALVE_MAX,
            "OUTPUT_DEADBAND": DEFAULT_PID_OUTPUT_DEADBAND,
            "INTEGRAL_ACCUMULATION_RANGE": DEFAULT_PID_INTEGRAL_ACCUMULATION_RANGE,
        },
        "FEEDFORWARD": {
            "WIND_COEFF": DEFAULT_PID_FF_WIND_COEFF,
            "TEMP_COEFF": DEFAULT_PID_FF_TEMP_COEFF,
            "SUN_COEFF": DEFAULT_PID_FF_SUN_COEFF,
            "WIND_CHILL_COEFF": DEFAULT_PID_FF_WIND_CHILL_COEFF,
            "BASE_TEMP_REF_OUTSIDE": DEFAULT_PID_BASE_TEMP_REF_OUTSIDE,
            "BASE_TEMP_BOILER": DEFAULT_PID_BASE_TEMP_BOILER,
        },
        "MQTT": {
            "BROKER": "broker",
            "PORT": 1883,
            "RESET_IMMUNE": True,
        },
    }

# --- Hardware Initialization Functions ---
from machine import Pin, I2C
from drivers.driver_mcp23017 import Portexpander, McpPin
from drivers.driver_lcd import LCD
from drivers.driver_HD44780 import LCD1602
from drivers.driver_rgbled import RGBLED
from controllers.controller_HID import HIDController
from machine import unique_id
import binascii
from machine import UART
import uos
import time
from machine import reset
import json
from managers.manager_logger import Logger

logger = Logger()

def unique_hardware_name():
    """Generate a unique name for the device."""
    try:
        name=binascii.hexlify(unique_id())
        return "OT-CTRL-"+name.decode()
    except Exception as e:
        return "OT-CTRL-GENERIC"

def HWi2c(cfg):
    """Initialize I2C bus and return the instance."""
    i2c_cfg = cfg.get("HARDWARE", "I2C")
    return I2C(i2c_cfg["ID"], 
              sda=Pin(i2c_cfg["SDA_PIN"]), 
              scl=Pin(i2c_cfg["SCL_PIN"]))

def HWMCP(i2c, cfg):
    """Initialize MCP23017 I/O expander and return the instance."""
    mcp_cfg = cfg.get("HARDWARE", "MCP")
    return Portexpander(i2c, mcp_cfg["ADDRESS"])

def HWRGBLed(mcp, cfg):
    """Initialize RGB LED pins and return the RGBLED instance."""
    led_cfg = cfg.get("HARDWARE", "RGBLED")
    use_mcp = led_cfg.get("MCPPIN", True)
    
    if use_mcp:
        led_red = McpPin(mcp, led_cfg["RED_PIN"], McpPin.OUT)
        led_green = McpPin(mcp, led_cfg["GREEN_PIN"], McpPin.OUT)
        led_blue = McpPin(mcp, led_cfg["BLUE_PIN"], McpPin.OUT)
    else:
        led_red = Pin(led_cfg["RED_PIN"], Pin.OUT)
        led_green = Pin(led_cfg["GREEN_PIN"], Pin.OUT)
        led_blue = Pin(led_cfg["BLUE_PIN"], Pin.OUT)
    
    return RGBLED(led_red, led_green, led_blue, initial_color="yellow")

def HWLCD(mcp, cfg) -> LCD:
    """Initialize LCD pins and return an LCD instance."""
    lcd_cfg = cfg.get("HARDWARE", "LCD")
    use_mcp = lcd_cfg.get("MCPPIN", True)
    
    if use_mcp:
        lcd_rw = McpPin(mcp, lcd_cfg["RW_PIN"], McpPin.OUT)
        lcd_rs = McpPin(mcp, lcd_cfg["RS_PIN"], McpPin.OUT)
        lcd_en = McpPin(mcp, lcd_cfg["EN_PIN"], McpPin.OUT)
        lcd_d4 = McpPin(mcp, lcd_cfg["D4_PIN"], McpPin.OUT)
        lcd_d5 = McpPin(mcp, lcd_cfg["D5_PIN"], McpPin.OUT)
        lcd_d6 = McpPin(mcp, lcd_cfg["D6_PIN"], McpPin.OUT)
        lcd_d7 = McpPin(mcp, lcd_cfg["D7_PIN"], McpPin.OUT)
    else:
        lcd_rw = Pin(lcd_cfg["RW_PIN"], Pin.OUT)
        lcd_rs = Pin(lcd_cfg["RS_PIN"], Pin.OUT)
        lcd_en = Pin(lcd_cfg["EN_PIN"], Pin.OUT)
        lcd_d4 = Pin(lcd_cfg["D4_PIN"], Pin.OUT)
        lcd_d5 = Pin(lcd_cfg["D5_PIN"], Pin.OUT)
        lcd_d6 = Pin(lcd_cfg["D6_PIN"], Pin.OUT)
        lcd_d7 = Pin(lcd_cfg["D7_PIN"], Pin.OUT)
    
    return LCD1602(lcd_rw, lcd_rs, lcd_en, lcd_d4, lcd_d5, lcd_d6, lcd_d7, 
                  cols=lcd_cfg["COLS"], rows=lcd_cfg["ROWS"])

def HWButtons(mcp, cfg):
    """Initialize button pins and return the HIDController instance."""
    btn_cfg = cfg.get("HARDWARE", "BUTTONS")
    use_mcp = btn_cfg.get("MCPPIN", True)
    
    if use_mcp:
        pin_mode = McpPin.IN
        pull_mode = McpPin.PULL_UP
        button_left = McpPin(mcp, btn_cfg["LEFT_PIN"], pin_mode, pull_mode)
        button_up = McpPin(mcp, btn_cfg["UP_PIN"], pin_mode, pull_mode)
        button_down = McpPin(mcp, btn_cfg["DOWN_PIN"], pin_mode, pull_mode)
        button_right = McpPin(mcp, btn_cfg["RIGHT_PIN"], pin_mode, pull_mode)
        button_select = McpPin(mcp, btn_cfg["SELECT_PIN"], pin_mode, pull_mode)
    else:
        pin_mode = Pin.IN
        pull_mode = Pin.PULL_UP
        button_left = Pin(btn_cfg["LEFT_PIN"], pin_mode, pull_mode)
        button_up = Pin(btn_cfg["UP_PIN"], pin_mode, pull_mode)
        button_down = Pin(btn_cfg["DOWN_PIN"], pin_mode, pull_mode)
        button_right = Pin(btn_cfg["RIGHT_PIN"], pin_mode, pull_mode)
        button_select = Pin(btn_cfg["SELECT_PIN"], pin_mode, pull_mode)
    
    return HIDController(button_left, button_up, button_down, button_right, button_select)

def HWUART(cfg):
    """Initialize UART and return the instance."""
    uart_cfg = cfg.get("HARDWARE", "UART")
    return UART(uart_cfg["ID"], 
               baudrate=uart_cfg["BAUDRATE"],
               tx=Pin(uart_cfg["TX_PIN"]), 
               rx=Pin(uart_cfg["RX_PIN"]), 
               timeout=10, timeout_char=10)

def ConfigFileName():
    """Returns the appropriate configuration filename (now JSON)."""
    return CONFIG_FILENAME

def factory_reset(display, led):
    """Performs a factory reset while preserving sections marked as RESET_IMMUNE."""
    cache_file = "hm_device_cache.json"

    logger.info("--- Factory Reset Initiated ---")
    if display: display.show_message("Factory Reset", "Working...")
    if led: led.direct_send_color("blue")

    # 1. Delete Homematic Device Cache
    try:
        uos.remove(cache_file)
        logger.info(f"Deleted cache file: {cache_file}")
    except OSError as e:
        if e.args[0] == 2:  # ENOENT
            logger.warning(f"Cache file not found (already deleted?): {cache_file}")
        else:
            logger.error(f"Error deleting cache file {cache_file}: {e}")
            if display: display.show_message("Reset Error", "Cache delete fail")
            time.sleep(3)

    # 2. Load existing config to preserve immune sections
    preserved_config = {}
    try:
        with open(ConfigFileName(), 'r') as f:
            try:
                current_config = json.load(f)
                if isinstance(current_config, dict):
                    # Preserve sections marked as RESET_IMMUNE
                    for section, values in current_config.items():
                        if isinstance(values, dict) and values.get("RESET_IMMUNE", False):
                            preserved_config[section] = values
            except json.JSONDecodeError:
                logger.warning("Could not parse existing config, will use factory defaults")
    except OSError:
        logger.warning("Could not read existing config, will use factory defaults")

    # 3. Create new config with factory defaults but preserve immune sections
    new_config = get_factory_config()
    
    # Override with preserved settings
    for section, values in preserved_config.items():
        if section in new_config:
            # Keep the RESET_IMMUNE flag from factory defaults
            immune_flag = new_config[section].get("RESET_IMMUNE", False)
            new_config[section] = values
            new_config[section]["RESET_IMMUNE"] = immune_flag

    # 4. Write the new config
    logger.info(f"Writing new config to {ConfigFileName()} (preserving immune sections)...")
    try:
        with open(ConfigFileName(), 'w') as f:
            json.dump(new_config, f)
        logger.info(f"Successfully wrote new config to {ConfigFileName()}")

        # 5. Final steps before reboot
        logger.info("Factory reset complete. Rebooting in 5 seconds...")
        if display: display.show_message("Factory Reset", "OK. Rebooting...")
        if led: led.direct_send_color("green")
        time.sleep(5)
        reset()

    except Exception as e:
        logger.error(f"FATAL: Error writing config: {e}")
        if display: display.show_message("Reset Error", "Config write fail")
        if led: led.direct_send_color("red")
        time.sleep(3)
