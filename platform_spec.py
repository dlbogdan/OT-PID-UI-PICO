# Hardware configuration constants
I2C_ID = 1
I2C_SDA_PIN = 14
I2C_SCL_PIN = 15
MCP_ADDRESS = 0x20

#OPENTHERM UART configuration
OT_UART_ID = 0
OT_UART_TX_PIN = 16
OT_UART_RX_PIN = 17
OT_UART_BAUDRATE = 9600

# RGB LED pin configuration
RGBLED_RED_PIN = 6
RGBLED_GREEN_PIN = 8
RGBLED_BLUE_PIN = 7

# Button pin configuration
BUTTON_LEFT_PIN = 4
BUTTON_UP_PIN = 3
BUTTON_DOWN_PIN = 2
BUTTON_RIGHT_PIN = 1
BUTTON_SELECT_PIN = 0

# LCD pin configuration
LCD_RW_PIN = 14
LCD_RS_PIN = 15
LCD_EN_PIN = 13
LCD_D4_PIN = 12
LCD_D5_PIN = 11
LCD_D6_PIN = 10
LCD_D7_PIN = 9

# LCD dimensions
LCD_COLS = 16
LCD_ROWS = 2


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

def unique_hardware_name():
    """Generate a unique name for the device."""
    try:
        name=binascii.hexlify(unique_id())
        return "OT-CTRL-"+name.decode()
    except Exception as e:
        return "OT-CTRL-GENERIC"

def HWi2c():
    """Initialize I2C bus and return the instance."""
    return I2C(I2C_ID, sda=Pin(I2C_SDA_PIN), scl=Pin(I2C_SCL_PIN))

def HWMCP(i2c):
    """Initialize MCP23017 I/O expander and return the instance."""
    return Portexpander(i2c, MCP_ADDRESS)

def HWRGBLed(mcp):
    """Initialize RGB LED pins and return the RGBLED instance."""
    led_red = McpPin(mcp, RGBLED_RED_PIN, McpPin.OUT)
    led_green = McpPin(mcp, RGBLED_GREEN_PIN, McpPin.OUT)
    led_blue = McpPin(mcp, RGBLED_BLUE_PIN, McpPin.OUT)
    return RGBLED(led_red, led_green, led_blue, initial_color="yellow")

def HWLCD(mcp) -> LCD:
    """Initialize LCD pins and return an LCD instance.
    
    Returns:
        LCD: An instance of an LCD display (currently LCD1602)
    """
    lcd_rw = McpPin(mcp, LCD_RW_PIN, McpPin.OUT)
    lcd_rs = McpPin(mcp, LCD_RS_PIN, McpPin.OUT)
    lcd_en = McpPin(mcp, LCD_EN_PIN, McpPin.OUT)
    lcd_d4 = McpPin(mcp, LCD_D4_PIN, McpPin.OUT)
    lcd_d5 = McpPin(mcp, LCD_D5_PIN, McpPin.OUT)
    lcd_d6 = McpPin(mcp, LCD_D6_PIN, McpPin.OUT)
    lcd_d7 = McpPin(mcp, LCD_D7_PIN, McpPin.OUT)
    return LCD1602(lcd_rw, lcd_rs, lcd_en, lcd_d4, lcd_d5, lcd_d6, lcd_d7, cols=LCD_COLS, rows=LCD_ROWS)

def HWButtons(mcp):
    """Initialize button pins and return the HIDController instance."""
    button_left = McpPin(mcp, BUTTON_LEFT_PIN, McpPin.IN, McpPin.PULL_UP)
    button_up = McpPin(mcp, BUTTON_UP_PIN, McpPin.IN, McpPin.PULL_UP)
    button_down = McpPin(mcp, BUTTON_DOWN_PIN, McpPin.IN, McpPin.PULL_UP)
    button_right = McpPin(mcp, BUTTON_RIGHT_PIN, McpPin.IN, McpPin.PULL_UP)
    button_select = McpPin(mcp, BUTTON_SELECT_PIN, McpPin.IN, McpPin.PULL_UP)
    return HIDController(button_left, button_up, button_down, button_right, button_select)

def HWUART():
    """Initialize UART and return the instance."""
    return UART(OT_UART_ID, baudrate=OT_UART_BAUDRATE, tx=Pin(OT_UART_TX_PIN), rx=Pin(OT_UART_RX_PIN), timeout=10, timeout_char=10)

def ConfigFileName(factory:bool=False):
    if factory:
        return "config_factory.txt"
    else:
        return "config.txt"

DEFAULT_FACTORY_CONFIG = {
    "DEVICE": {
        "DEBUG": "1",
    },
    "WIFI": {
        "SSID": "",
        "PASS": "",
    },
    "CCU3": {
        "IP": "0.0.0.0",
        "USER": "",
        "PASS": "",
        "VALVE_DEVTYPE": "HmIP-eTRV",
        "WEATHER_DEVTYPE": "HmIP-SWO",
    },
    "OT": {
        "MAX_HEATING_SETPOINT": "72.0",
        "MANUAL_HEATING_SETPOINT": "55.0",
        "DHW_SETPOINT": "50.0",
        "ENABLE_CONTROLLER": "False",
        "ENABLE_HEATING": "False",
        "ENABLE_DHW": "True",
    },
    "AUTOH": {
        "ENABLE": "True",
        "OFF_TEMP": "20.0",
        "OFF_VALVE_LEVEL": "6.0",
        "ON_TEMP": "17.0",
        "ON_VALVE_LEVEL": "8.0",
    },
    "MQTT": {
        "BROKER": "",
        "PORT": "1883",
    },
}
# ------------------------------------
