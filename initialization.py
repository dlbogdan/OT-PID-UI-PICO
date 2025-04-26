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
from controllers.controller_pid import PIDController

logger = Logger()


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

def setup_gui(gui, cfg, wifi, hm, ot_manager):
    """Builds the menu structure and sets up GUI modes."""
    logger.info("Setting up GUI...")
    
    def save_and_reboot():
        gui.display.show_message("Action", "Saving & Reboot")
        if not cfg.save_config(): # Try one last save
            logger.error("Failed to save config before reboot.")
        else:
            logger.info("Config saved before reboot.")
        time.sleep(1)
        reset()

    # --- Build Menu Structure --- # 
    menu_items = [
        Menu("Network", [
            TextField("WiFi SSID", cfg.get("WIFI", "SSID", ""), lambda v: cfg.set("WIFI", "SSID", v)),
            TextField("WiFi Pass", cfg.get("WIFI", "PASS", ""), lambda v: cfg.set("WIFI", "PASS", v)),
        ]),
        Menu("Homematic", [
            IPAddressField("CCU3 IP", cfg.get("CCU3", "IP", "0.0.0.0"), lambda v: cfg.set("CCU3", "IP", v)),
            TextField("CCU3 User", cfg.get("CCU3", "USER", ""), lambda v: cfg.set("CCU3", "USER", v)),
            TextField("CCU3 Pass", cfg.get("CCU3", "PASS", ""), lambda v: cfg.set("CCU3", "PASS", v)),
            TextField("Valve Type", cfg.get("CCU3", "VALVE_DEVTYPE", "HmIP-eTRV"), lambda v: cfg.set("CCU3", "VALVE_DEVTYPE", v)),
            TextField("Weather Type", cfg.get("CCU3", "WEATHER_DEVTYPE", "HmIP-SWO"), lambda v: cfg.set("CCU3", "WEATHER_DEVTYPE", v)),
            Action("Rescan", hm.force_rescan),
        ]),
        Menu("OpenTherm", [
            FloatField("Max Heating SP", cfg.get("OT", "MAX_HEATING_SETPOINT", 72.0), lambda v: cfg.set("OT", "MAX_HEATING_SETPOINT", v)),
            FloatField("Manual Heating SP", cfg.get("OT", "MANUAL_HEATING_SETPOINT", 55.0), lambda v: cfg.set("OT", "MANUAL_HEATING_SETPOINT", v)),
            FloatField("DHW Setpoint", cfg.get("OT", "DHW_SETPOINT", 50.0), lambda v: cfg.set("OT", "DHW_SETPOINT", v)),
            BoolField("Takeover Control", cfg.get("OT", "ENABLE_CONTROLLER", False), lambda v: cfg.set("OT", "ENABLE_CONTROLLER", v)),
            BoolField("Enable Heating", cfg.get("OT", "ENABLE_HEATING", False), lambda v: cfg.set("OT", "ENABLE_HEATING", v)), # Manual heating enable
            BoolField("Enable DHW", cfg.get("OT", "ENABLE_DHW", True), lambda v: cfg.set("OT", "ENABLE_DHW", v)),
            BoolField("Enforce DHW SP", cfg.get("OT", "ENFORCE_DHW_SETPOINT", False), lambda v: cfg.set("OT", "ENFORCE_DHW_SETPOINT", v)),
        ]),
        Menu("Auto Heating", [
            BoolField("Enable Auto", cfg.get("AUTOH", "ENABLE", True), lambda v: cfg.set("AUTOH", "ENABLE", v)),
            FloatField("Off Temp >=", cfg.get("AUTOH", "OFF_TEMP", 20.0), lambda v: cfg.set("AUTOH", "OFF_TEMP", v)),
            FloatField("Off Valve <", cfg.get("AUTOH", "OFF_VALVE_LEVEL", 6.0), lambda v: cfg.set("AUTOH", "OFF_VALVE_LEVEL", v)),
            FloatField("On Temp <", cfg.get("AUTOH", "ON_TEMP", 17.0), lambda v: cfg.set("AUTOH", "ON_TEMP", v)),
            FloatField("On Valve >", cfg.get("AUTOH", "ON_VALVE_LEVEL", 8.0), lambda v: cfg.set("AUTOH", "ON_VALVE_LEVEL", v)),
        ]),
        Menu("PID Config", [
            FloatField("Prop. Gain (Kp)", cfg.get("PID", "KP", 0.05), lambda v: cfg.set("PID", "KP", v), precision=5),
            FloatField("Integ. Gain (Ki)", cfg.get("PID", "KI", 0.002), lambda v: cfg.set("PID", "KI", v), precision=5),
            FloatField("Deriv. Gain (Kd)", cfg.get("PID", "KD", 0.01), lambda v: cfg.set("PID", "KD", v), precision=5),
            FloatField("Setpoint (Valve%)", cfg.get("PID", "SETPOINT", 25.0), lambda v: cfg.set("PID", "SETPOINT", v)),
            FloatField("Valve Min %", cfg.get("PID", "VALVE_MIN", 8.0), lambda v: cfg.set("PID", "VALVE_MIN", v)),
            FloatField("Valve Max %", cfg.get("PID", "VALVE_MAX", 70.0), lambda v: cfg.set("PID", "VALVE_MAX", v)),
            FloatField("FF Wind Coeff", cfg.get("PID", "FF_WIND_COEFF", 0.1), lambda v: cfg.set("PID", "FF_WIND_COEFF", v)),
            FloatField("FF Temp Coeff", cfg.get("PID", "FF_TEMP_COEFF", 1.1), lambda v: cfg.set("PID", "FF_TEMP_COEFF", v)),
            FloatField("FF Sun Coeff", cfg.get("PID", "FF_SUN_COEFF", 0.0001), lambda v: cfg.set("PID", "FF_SUN_COEFF", v)),
            FloatField("FF Wind Interact", cfg.get("PID", "FF_WIND_INTERACTION_COEFF", 0.008), lambda v: cfg.set("PID", "FF_WIND_INTERACTION_COEFF", v), precision=4),
            FloatField("Base Temp Outside", cfg.get("PID", "BASE_TEMP_REF_OUTSIDE", 10.0), lambda v: cfg.set("PID", "BASE_TEMP_REF_OUTSIDE", v)),
            FloatField("Base Temp Boiler", cfg.get("PID", "BASE_TEMP_BOILER", 45.0), lambda v: cfg.set("PID", "BASE_TEMP_BOILER", v)),
        ]),
        Menu("Device", [
            Action("View Log", lambda: gui.switch_mode("logview")),
            Action("Reset Error limiter", logger.reset_error_rate_limiter),
            Action("Reboot Device", reset),
            Action("Save & Reboot", save_and_reboot),
            Action("Factory defaults", lambda: factory_reset(gui.display, gui.led, cfg, hm)),
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
    # Page 3: Setpoints (using manager getters)
    mon.add_page(Page(lambda: f"DHW SP: {ot_manager.get_dhw_setpoint()}",
                       lambda: f" CH SP: {ot_manager.get_control_setpoint()}"))
    # Page 4: OT controller status (using manager getters)
    mon.add_page(Page(lambda: f"OT: {'On' if ot_manager.is_active() else 'Off'} Conn: {'Yes' if ot_manager.is_boiler_connected() else 'No'}",
                       lambda: f"CH: {'On' if ot_manager.is_ch_enabled() else 'Off'} DHW: {'On' if ot_manager.is_dhw_enabled() else 'Off'}"))
    # Page 5: Room with max valve opening
    mon.add_page(Page(lambda: f"Room: {hm.max_valve_room_name}",
                       lambda: f"Max Valve: {hm.max_valve:.1f}%" if hm.is_ccu_connected() else "(CCU Offline)"))
    # Page 6: Weather sensor data
    mon.add_page(Page(lambda: f"Temp: {hm.temperature:.1f}C" if hm.has_weather_data and hm.temperature is not None else "Temperature: N/A",
                       lambda: f"Wind: {hm.wind_speed:.1f}km/h" if hm.has_weather_data and hm.wind_speed is not None else "Wind: N/A"))
    # Page 7: Weather sensor illumination
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
    cfg = ConfigManager(ConfigFileName(), ConfigFileName(factory=True))
    
    # Use get() method directly for initial service setup
    wifi = WiFiManager(
        cfg.get("WIFI", "SSID"), 
        cfg.get("WIFI", "PASS"), 
        unique_hardware_name()[:15]
    )
    hm = HomematicDataService(
        f"http://{cfg.get('CCU3', 'IP')}/api/homematic.cgi",
        cfg.get("CCU3", "USER"), 
        cfg.get("CCU3", "PASS"), 
        cfg.get("CCU3", "VALVE_DEVTYPE", "HmIP-eTRV"),
        weather_device_type=str(cfg.get("CCU3", "WEATHER_DEVTYPE", "HmIP-SWO")) # Keep str conversion for safety
    )
    logger.info("Instantiating PID Controller...")
    pid = PIDController(
        # Use cfg_mgr.get directly - type hint in ConfigManager should help linter
        kp=cfg.get("PID", "KP", 0.05), 
        ki=cfg.get("PID", "KI", 0.002),
        kd=cfg.get("PID", "KD", 0.01),
        setpoint=cfg.get("PID", "SETPOINT", 25.0),
        output_min=35.0, # Keep hardcoded or load if needed
        output_max=cfg.get("OT", "MAX_HEATING_SETPOINT", 72.0), # Get OT max heating SP
        integral_min=None, # Keep default for now
        integral_max=None, # Keep default for now
        ff_wind_coeff=cfg.get("PID", "FF_WIND_COEFF", 0.1),
        ff_temp_coeff=cfg.get("PID", "FF_TEMP_COEFF", 1.1),
        ff_sun_coeff=cfg.get("PID", "FF_SUN_COEFF", 0.0001),
        ff_wind_interaction_coeff=cfg.get("PID", "FF_WIND_INTERACTION_COEFF", 0.008),
        base_temp_ref_outside=cfg.get("PID", "BASE_TEMP_REF_OUTSIDE", 10.0),
        base_temp_boiler=cfg.get("PID", "BASE_TEMP_BOILER", 45.0),
        valve_input_min=cfg.get("PID", "VALVE_MIN", 8.0),
        valve_input_max=cfg.get("PID", "VALVE_MAX", 70.0),
        time_factor=1.0 # Use real-time for actual operation
    )
    logger.info("PID Controller instantiated.")
    logger.info("Services initialised.")
    # Return manager and services
    return cfg, wifi, hm, pid
