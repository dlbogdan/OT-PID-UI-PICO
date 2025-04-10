# PicoW Homematic/OpenTherm Controller & UI

## Overview

This project runs on a Raspberry Pi Pico W and acts as an intelligent heating controller. Its primary goal is to **control an OpenTherm-compatible boiler** by setting the optimal heating water temperature based on the **real-time heat demand** requested by Homematic (HmIP-eTRV) radiator valves distributed throughout a house.

It monitors the valve opening percentages from a Homematic CCU3, calculates demand, potentially incorporates outdoor weather data (temperature, humidity, wind speed) from a Homematic weather sensor, and sends the appropriate setpoint to the boiler via an OpenTherm Gateway. The system provides a user interface on a 16x2 LCD display for monitoring and configuration.

## Features

*   **WiFi Connection Management:** Connects the Pico W to your local WiFi network.
*   **Homematic CCU3 Communication:** Interacts asynchronously with a Homematic CCU3 (or compatible, like RaspberryMatic) via its JSON-RPC API.
    *   Supports CCU3 username/password authentication.
    *   Handles session management and automatic re-login on expiry.
*   **Valve Device Discovery & Monitoring:**
    *   Discovers specified Homematic valve devices (e.g., `HmIP-eTRV`).
    *   Assigns discovered devices to their corresponding rooms (if configured in CCU).
    *   Periodically fetches current valve opening percentages (`LEVEL`).
    *   Calculates and displays average/max valve opening.
    *   Identifies and displays the room with the highest current demand (max valve opening).
*   **Persistent Device Cache:** Saves the discovered valve device list (`iface`, `addr`, `room_name`) to `hm_device_cache.json` on the Pico W's flash memory to speed up subsequent boots.
*   **Weather Sensor Integration (Planned):** Designed to incorporate data from a Homematic weather sensor (temperature, humidity, wind speed) for more advanced control logic.
*   **PID Control (Core Logic):** Uses PID parameters (Kp, Ki, Kd - configurable placeholders for now) to calculate the target heating water setpoint based on maximum valve demand and potentially outdoor weather conditions.
*   **OpenTherm Gateway Communication (Planned):** Intended to send the calculated setpoint temperature to the boiler via an OpenTherm Gateway interface. *(Note: Specific OT Gateway communication logic might still be under development)*.
*   **LCD User Interface (16x2):**
    *   Custom GUI framework (`gui.py`) with different modes.
    *   **Monitoring Mode:** Auto-refreshes pages showing:
        *   Network Status (IP or status) & CCU Connection Status
        *   Valve Statistics (Avg%, Max%, Count)
        *   PID Parameters (Kp, Ki, Kd) & Calculated Output (OUT)
        *   Room with Maximum Valve Opening
    *   **Navigation Mode:** Browse hierarchical menus using buttons.
    *   **Editing Mode:** Edit configuration values directly on the device using buttons:
        *   Text Fields (WiFi SSID/Pass, CCU User/Pass, Valve Type)
        *   IP Address Fields (CCU IP)
        *   Numeric Fields (Integers, Floats)
        *   Boolean Fields
*   **Button Input:** Uses 5 push buttons (Left, Up, Down, Right, Select) via MCP23017 for UI navigation and editing. Supports short press, long press, and repeat for Up/Down.
*   **Configuration Management:**
    *   Reads settings from `config.txt`.
    *   Allows editing configuration via the UI menu, saving changes persistently.
    *   Uses `config_factory.txt` for default values.
*   **Factory Reset:** Menu option to delete the device cache, restore `config.txt` from `config_factory.txt` (creating it from hardcoded defaults if missing), and reboot.
*   **Status Indication:** Uses an RGB LED to show system status (Booting, WiFi Connecting, WiFi OK/CCU OK, WiFi OK/CCU Error, WiFi Error).
*   **Asynchronous Operation:** Uses `uasyncio` for non-blocking operation of network tasks, UI updates, and sensor polling.
*   **Error Handling:** Catches and handles specific network errors (e.g., `EHOSTUNREACH`) to pause network requests gracefully. Includes a fatal error handler.

## Hardware Requirements

*   Raspberry Pi Pico W
*   MCP23017 I/O Expander (connected via I2C)
*   HD44780-compatible 16x2 LCD Display (4-bit mode, connected via MCP23017)
*   5 x Push Buttons (connected via MCP23017 with pull-ups enabled)
*   1 x Common Cathode RGB LED (connected via MCP23017)
*   **OpenTherm Gateway:** A hardware interface compatible with your boiler's OpenTherm port and connectable to the Pico W (e.g., via UART). *(Specific model/wiring may vary)*.
*   Appropriate power supply for Pico W and peripherals.
*   Resistors, wires, breadboard/PCB as needed.
*   **Homematic Infrastructure:**
    *   Homematic CCU3 (or compatible, e.g., RaspberryMatic). **CCU2 is likely not supported.**
    *   Homematic HmIP-eTRV radiator valves (or the type specified in `config.txt`).
    *   (Optional) Homematic Weather Sensor.
    *   CCU accessible on the same network as the Pico W.

## Software Setup

1.  **Install MicroPython:** Flash the Raspberry Pi Pico W with the **latest stable MicroPython firmware** (Tested with v1.24.1 or newer is recommended). Download from [micropython.org](https://micropython.org/download/RPI_PICO_W/).
2.  **Copy Files:** Copy all the project files (`.py`, `config.txt`, `config_factory.txt`) to the root directory of the Pico W's internal flash storage (e.g., using Thonny IDE or `rshell`).

## Configuration

1.  **`config.txt`:** This file stores the main operational settings in an INI-like format.
    *   **[WIFI]**
        *   `SSID`: Your WiFi network name.
        *   `PASS`: Your WiFi password.
    *   **[CCU3]**
        *   `IP`: IP address of your Homematic CCU3.
        *   `USER`: Username for CCU3 JSON-RPC API (leave blank if none).
        *   `PASS`: Password for CCU3 JSON-RPC API (leave blank if none).
        *   `VALVE_DEVTYPE`: The Homematic device type string for your radiator valves (e.g., `HmIP-eTRV`).
    *   **[TEST]** (Optional section for testing values)
        *   `INT`, `FLOAT`, `BOOL`

2.  **Initial Setup:**
    *   **Recommended:** Edit `config.txt` directly on your computer *before* copying it to the Pico W for the first time, filling in your WiFi and CCU details.
    *   **Alternatively:** Boot the Pico W with the default `config.txt`. The device will likely fail to connect. Use the UI menu (`Main Menu` -> `Network` / `Homematic`) to enter your details. Changes made via the menu are saved immediately to `config.txt`.

3.  **`config_factory.txt`:**
    *   This file holds the default configuration used during a Factory Reset.
    *   If this file is missing when a Factory Reset is triggered, it will be automatically created using hardcoded defaults defined in `main.py`. You should ensure these hardcoded defaults are appropriate for your setup.

4.  **`hm_device_cache.json`:**
    *   This file is created automatically by the system after the first successful discovery of Homematic devices.
    *   It stores the interface, address, and room name for each discovered valve device.
    *   It is used on subsequent boots to avoid the lengthy discovery process.
    *   It is deleted during a Factory Reset or when "Rescan" from "Homematic" menu is selected.

## Usage

1.  **Boot-up:**
    *   Connect the Pico W to power.
    *   The LED will turn Red  uring initialization.
    *   The LCD will show "System Booting".
    *   The system attempts to connect to WiFi (LED blinks Red if connecting/failed, Magenta if WiFi OK but CCU fails, slow Green blink if WiFi and CCU OK).
    *   Once running, the system defaults to the Monitoring Mode display.
2.  **Button Functions:**
    *   **UP/DOWN:** Navigate menu items / cycle monitoring pages / change values in edit mode. (Hold for repeat in edit mode).
    *   **LEFT:** Go back up one menu level / cancel edit (long press) / exit Monitoring mode to Main Menu. (Delete character in text edit mode).
    *   **RIGHT:** Enter submenu / move cursor right or add character in text edit mode.
    *   **SELECT:** Select menu item / Enter edit mode for a field / Confirm edit.
3.  **Monitoring Mode:** Cycles through pages automatically showing key status information. Use UP/DOWN to cycle manually. Press SELECT to enter the Main Menu.
4.  **Menu Navigation:** Use UP/DOWN to highlight items, RIGHT/SELECT to enter submenus or edit fields, LEFT to go back.
5.  **LED Status Codes:**
    *   **Red (Solid):** Booting / Initializing.
    *   **Red (Blinking):** WiFi connection error or disconnected.
    *   **Magenta (Blinking):** WiFi connected, but error communicating with CCU3 (login failure, session issue, etc.).
    *   **Green (Slow Blink):** WiFi connected and CCU3 communication OK.
    *   **Blue (Solid):** Factory Reset in progress.

## Homematic Requirements

*   Requires a **Homematic CCU3** or compatible (e.g., RaspberryMatic). CCU2 is not expected to work due to potential API differences.
*   Ensure the CCU's JSON-RPC API is accessible from the Pico W on the network (check firewall settings if necessary). No specific addon is required for the core functionality.
*   User permissions on the CCU might be required for the API user if you configure one.
*   HTTPS communication with the CCU is **not currently supported** due to potential memory constraints on the Pico W. Ensure your CCU allows HTTP access for the API.

## Troubleshooting

*   **No WiFi Connection (Red Blink):** Double-check SSID and Password in `config.txt` or via the menu. Ensure your WiFi network is 2.4GHz and accessible. Check Pico W antenna placement.
*   **CCU Connection Error (Magenta Blink):** Verify CCU IP Address, Username, and Password. Ensure the CCU is powered on and reachable on the network (try pinging it). Check CCU firewall settings. Consider a "Rescan Homematic" from the menu if the cache might be stale.
*   **Device Discovery Fails:** Check the `VALVE_DEVTYPE` in `config.txt` matches your valve devices exactly. Ensure devices are paired and reachable by the CCU.
*   **UI Unresponsive:** Check power supply and wiring. Monitor serial output (if connected via USB) for error messages.
