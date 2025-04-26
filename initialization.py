import utime as time
from machine import reset

# Project modules
from platform_spec import (
    HWi2c, HWMCP, HWLCD, HWRGBLed, HWButtons, HWUART,
    unique_hardware_name, ConfigFileName
)
from controllers.controller_display import DisplayController
from controllers.controller_otgw import OpenThermController
from managers.manager_config import ConfigManager, factory_reset
from managers.manager_wifi import WiFiManager
from managers.manager_otgw import OpenThermManager
from services.service_homematic_rpc import HomematicDataService
from gui import (
    GUIManager, NavigationMode, EditingMode,
    Menu, FloatField, BoolField, Action, IPAddressField, TextField,
    MonitoringMode, Page, LogView,
)
from flags import DEVELOPMENT_MODE
from managers.manager_logger import Logger

logger = Logger()

# --------------------------------------------------------------------------- #
#  Fatal‑error handler
# --------------------------------------------------------------------------- #

# def handle_fatal_error(err_type, display, led, msg, development_mode=False):
#     """Logs fatal errors, updates display/LED, and reboots or halts."""
#     try:
#         if display:
#             display.show_message("FATAL ERROR", "REBOOTING..." if not development_mode else "ERROR")
#         if led:
#             led.direct_send_color("red")
#     except Exception as disp_exc:  # noqa: BLE001
#         logger.error(f"Display fail in fatal handler: {disp_exc}")
#     logger.fatal(err_type, msg,resetmachine=not development_mode)

#     time.sleep(2)
#     if development_mode:
#         logger.error(f"[DEV] FATAL {err_type}: {msg}")
#         # Loop indefinitely in development mode to allow debugging
#         while True:
#             time.sleep(1)
#     else:
#         reset()


# --------------------------------------------------------------------------- #
#  Hardware Initialisation
# --------------------------------------------------------------------------- #

def initialize_hardware():
    """Initialise I²C bus, peripherals and OpenTherm driver."""
    
    logger.info("Initialising hardware...")
    
    i2c = HWi2c()
    uart = HWUART()
    mcp = HWMCP(i2c)
    lcd = HWLCD(mcp)
    display = DisplayController(lcd)
    led = HWRGBLed(mcp)
    buttons = HWButtons(mcp)
    ot_controller = OpenThermController(uart)
    opentherm = OpenThermManager(ot_controller)

    logger.info("Hardware initialised.")
    
    # Return all initialized hardware components
    return display, led, buttons, opentherm


# --------------------------------------------------------------------------- #
#  Configuration Loading - Now handled internally by ConfigManager
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
#  GUI Setup
# --------------------------------------------------------------------------- #

def setup_gui(gui, cfg_mgr, wifi, hm, ot_manager, pid_instance=None):
    """Builds the menu structure and sets up GUI modes."""
    logger.info("Setting up GUI...")
    
    # Define save callback - calls cfg_mgr.set_value and handles PID gain updates
    def save(sec, key, val):
        logger.info(f"Saving config via GUI: Section={sec}, Key={key}, Value={val}")
        cfg_mgr.set_value(sec, key, val)
        logger.info(f"Config set for {sec}.{key}.")

        # --- Handle immediate PID gain updates --- 
        if pid_instance and sec == "PID" and key in ["KP", "KI", "KD"]:
            try:
                # Re-read all gains from config after saving the single key
                kp = cfg_mgr.get("PID", "KP", 0.05)
                ki = cfg_mgr.get("PID", "KI", 0.002)
                kd = cfg_mgr.get("PID", "KD", 0.01)
                logger.info(f"Applying updated PID gains: Kp={kp}, Ki={ki}, Kd={kd}")
                pid_instance.set_gains(kp, ki, kd)
            except Exception as e:
                logger.error(f"Failed to apply PID gains update: {e}")
        # --- End PID gain update --- 

    def save_and_reboot():
        gui.display.show_message("Action", "Saving & Reboot")
        if not cfg_mgr.save_config(): # Try one last save
            logger.error("Failed to save config before reboot.")
        else:
            logger.info("Config saved before reboot.")
        time.sleep(1)
        reset()

    # --- Build Menu Structure (using cfg_mgr.get) --- # 
    menu_items = [
        Menu("Network", [
            TextField("WiFi SSID", cfg_mgr.get("WIFI", "SSID", ""), lambda v: save("WIFI", "SSID", v)),
            TextField("WiFi Pass", cfg_mgr.get("WIFI", "PASS", ""), lambda v: save("WIFI", "PASS", v)),
        ]),
        Menu("Homematic", [
            IPAddressField("CCU3 IP", cfg_mgr.get("CCU3", "IP", "0.0.0.0"), lambda v: save("CCU3", "IP", v)),
            TextField("CCU3 User", cfg_mgr.get("CCU3", "USER", ""), lambda v: save("CCU3", "USER", v)),
            TextField("CCU3 Pass", cfg_mgr.get("CCU3", "PASS", ""), lambda v: save("CCU3", "PASS", v)),
            TextField("Valve Type", cfg_mgr.get("CCU3", "VALVE_DEVTYPE", "HmIP-eTRV"), lambda v: save("CCU3", "VALVE_DEVTYPE", v)),
            TextField("Weather Type", cfg_mgr.get("CCU3", "WEATHER_DEVTYPE", "HmIP-SWO"), lambda v: save("CCU3", "WEATHER_DEVTYPE", v)),
            Action("Rescan", hm.force_rescan),
        ]),
        Menu("OpenTherm", [
            FloatField("Max Heating SP", cfg_mgr.get("OT", "MAX_HEATING_SETPOINT", 72.0), lambda v: save("OT", "MAX_HEATING_SETPOINT", v)),
            FloatField("Manual Heating SP", cfg_mgr.get("OT", "MANUAL_HEATING_SETPOINT", 55.0), lambda v: save("OT", "MANUAL_HEATING_SETPOINT", v)),
            FloatField("DHW Setpoint", cfg_mgr.get("OT", "DHW_SETPOINT", 50.0), lambda v: save("OT", "DHW_SETPOINT", v)),
            BoolField("Takeover Control", cfg_mgr.get("OT", "ENABLE_CONTROLLER", False), lambda v: save("OT", "ENABLE_CONTROLLER", v)),
            BoolField("Enable Heating", cfg_mgr.get("OT", "ENABLE_HEATING", False), lambda v: save("OT", "ENABLE_HEATING", v)), # Manual heating enable
            BoolField("Enable DHW", cfg_mgr.get("OT", "ENABLE_DHW", True), lambda v: save("OT", "ENABLE_DHW", v)),
            BoolField("Enforce DHW SP", cfg_mgr.get("OT", "ENFORCE_DHW_SETPOINT", False), lambda v: save("OT", "ENFORCE_DHW_SETPOINT", v)),
        ]),
        Menu("Auto Heating", [
            BoolField("Enable Auto", cfg_mgr.get("AUTOH", "ENABLE", True), lambda v: save("AUTOH", "ENABLE", v)),
            FloatField("Off Temp >=", cfg_mgr.get("AUTOH", "OFF_TEMP", 20.0), lambda v: save("AUTOH", "OFF_TEMP", v)),
            FloatField("Off Valve <", cfg_mgr.get("AUTOH", "OFF_VALVE_LEVEL", 6.0), lambda v: save("AUTOH", "OFF_VALVE_LEVEL", v)),
            FloatField("On Temp <", cfg_mgr.get("AUTOH", "ON_TEMP", 17.0), lambda v: save("AUTOH", "ON_TEMP", v)),
            FloatField("On Valve >", cfg_mgr.get("AUTOH", "ON_VALVE_LEVEL", 8.0), lambda v: save("AUTOH", "ON_VALVE_LEVEL", v)),
        ]),
        Menu("PID Config", [
            FloatField("Prop. Gain (Kp)", cfg_mgr.get("PID", "KP", 0.05), lambda v: save("PID", "KP", v), precision=5),
            FloatField("Integ. Gain (Ki)", cfg_mgr.get("PID", "KI", 0.002), lambda v: save("PID", "KI", v), precision=5),
            FloatField("Deriv. Gain (Kd)", cfg_mgr.get("PID", "KD", 0.01), lambda v: save("PID", "KD", v), precision=5),
            FloatField("Setpoint (Valve%)", cfg_mgr.get("PID", "SETPOINT", 25.0), lambda v: save("PID", "SETPOINT", v)),
            FloatField("Valve Min %", cfg_mgr.get("PID", "VALVE_MIN", 8.0), lambda v: save("PID", "VALVE_MIN", v)),
            FloatField("Valve Max %", cfg_mgr.get("PID", "VALVE_MAX", 70.0), lambda v: save("PID", "VALVE_MAX", v)),
            FloatField("FF Wind Coeff", cfg_mgr.get("PID", "FF_WIND_COEFF", 0.1), lambda v: save("PID", "FF_WIND_COEFF", v)),
            FloatField("FF Temp Coeff", cfg_mgr.get("PID", "FF_TEMP_COEFF", 1.1), lambda v: save("PID", "FF_TEMP_COEFF", v)),
            FloatField("FF Sun Coeff", cfg_mgr.get("PID", "FF_SUN_COEFF", 0.0001), lambda v: save("PID", "FF_SUN_COEFF", v)),
            FloatField("FF Wind Interact", cfg_mgr.get("PID", "FF_WIND_INTERACTION_COEFF", 0.008), lambda v: save("PID", "FF_WIND_INTERACTION_COEFF", v), precision=4),
            FloatField("Base Temp Outside", cfg_mgr.get("PID", "BASE_TEMP_REF_OUTSIDE", 10.0), lambda v: save("PID", "BASE_TEMP_REF_OUTSIDE", v)),
            FloatField("Base Temp Boiler", cfg_mgr.get("PID", "BASE_TEMP_BOILER", 45.0), lambda v: save("PID", "BASE_TEMP_BOILER", v)),
        ]),
        Menu("Device", [
            Action("View Log", lambda: gui.switch_mode("logview")),
            Action("Reset Error limiter", logger.reset_error_rate_limiter),
            Action("Reboot Device", reset),
            Action("Save & Reboot", save_and_reboot),
            Action("Factory defaults", lambda: factory_reset(gui.display, gui.led, cfg_mgr, hm)),
        ]),
    ]

    if DEVELOPMENT_MODE:
        menu_items.append(Menu("Debug", [
            Action("Force wifi disconnect", wifi.disconnect), # Assuming wifi has disconnect
            Action("Fake Error", lambda: logger.error("Fake Error Triggered via Menu")),
        ]))

    root_menu = Menu("Main Menu", menu_items)

    # --- Add GUI Modes --- #
    gui.add_mode("navigation", NavigationMode(root_menu))
    gui.add_mode("editing", EditingMode())

    mon = MonitoringMode(refresh_interval_ms=250)
    # Page 1: Network / CCU status
    mon.add_page(Page(lambda: f"Net: {wifi.get_ip() or 'NA'}",
                       lambda: f"CCU: {hm.is_ccu_connected()}"))
    # Page 2: Valve status
    mon.add_page(Page(lambda: (f"Avg: {hm.avg_valve:.1f}%" if hm.is_ccu_connected() else "Valve Status"),
                       lambda: (f"Max: {hm.max_valve:.1f}% {hm.valve_devices}/{hm.reporting_valves}" if hm.is_ccu_connected() else "CCU Offline")))
    # Page 3: PID constants (Imported from main for now)
    # mon.add_page(Page(lambda: f"Kp: {Kp:.2f} Ki: {Ki:.2f}",
    #                    lambda: f"Kd: {Kd:.2f} OUT: {OUT:.2f}"))
    # Page 4: Setpoints (using manager getters)
    mon.add_page(Page(lambda: f"DHW SP: {ot_manager.get_dhw_setpoint()}",
                       lambda: f"Control SP: {ot_manager.get_control_setpoint()}"))
    # Page 5: OT controller status (using manager getters)
    mon.add_page(Page(lambda: f"OT State: {'On' if ot_manager.is_active() else 'Off'}",
                       lambda: f"CH: {'On' if ot_manager.is_ch_enabled() else 'Off'} DHW: {'On' if ot_manager.is_dhw_enabled() else 'Off'}"))
    # Page 6: Room with max valve opening
    mon.add_page(Page(lambda: f"Room: {hm.max_valve_room_name}",
                       lambda: f"Max Valve: {hm.max_valve:.1f}%" if hm.is_ccu_connected() else "(CCU Offline)"))
    
    # Page 7: Weather sensor data
    mon.add_page(Page(lambda: f"Temp: {hm.temperature:.1f}C" if hm.has_weather_data and hm.temperature is not None else "Temperature: N/A",
                       lambda: f"Wind: {hm.wind_speed:.1f}km/h" if hm.has_weather_data and hm.wind_speed is not None else "Wind: N/A"))
    
    # Page 8: Weather sensor illumination
    mon.add_page(Page(lambda: f"Sun: {hm.illumination:.0f}lux" if hm.has_weather_data and hm.illumination is not None else "Illumination: N/A",
                       lambda: f"Weather: {'Online' if hm.has_weather_data else 'Offline'}"))

    gui.add_mode("monitoring", mon)

    log_view = LogView("log.txt", gui.display.rows, gui.display.cols)
    gui.add_mode("logview", log_view)

    gui.switch_mode("monitoring")
    logger.info("GUI setup complete.")


# --------------------------------------------------------------------------- #
#  Service Initialisation
# --------------------------------------------------------------------------- #

def initialize_services():
    """Initialises configuration manager, loads config, and sets up services."""
    logger.info("Initialising services...")
    cfg_mgr = ConfigManager(ConfigFileName(), ConfigFileName(factory=True))
    
    # Use get() method directly for initial service setup
    wifi = WiFiManager(
        cfg_mgr.get("WIFI", "SSID", ""), 
        cfg_mgr.get("WIFI", "PASS", ""), 
        unique_hardware_name()[:15]
    )
    hm = HomematicDataService(
        f"http://{cfg_mgr.get('CCU3', 'IP', '0.0.0.0')}/api/homematic.cgi",
        cfg_mgr.get("CCU3", "USER", ""), 
        cfg_mgr.get("CCU3", "PASS", ""), 
        cfg_mgr.get("CCU3", "VALVE_DEVTYPE", "HmIP-eTRV"),
        weather_device_type=str(cfg_mgr.get("CCU3", "WEATHER_DEVTYPE", "HmIP-SWO")) # Keep str conversion for safety
    )

    logger.info("Services initialised.")
    # Return manager and services
    return cfg_mgr, wifi, hm
