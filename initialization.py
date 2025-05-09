"""
Initialization module for OT-PID-UI-PICO.
"""

import utime as time
from machine import reset

# Project modules
from platform_spec import (
    HWi2c, HWMCP, HWLCD, HWRGBLed, HWButtons, HWUART,
    unique_hardware_name, ConfigFileName, factory_reset
)
from controllers.controller_display import DisplayController
from controllers.controller_otgw import OpenThermController
from controllers.controller_heating import HeatingController
from managers.manager_config import ConfigManager
from managers.manager_wifi import WiFiManager
from managers.manager_otgw import OpenThermManager
from services.service_homematic_rpc import HomematicDataService
from managers.gui import (
    GUIManager, NavigationMode, EditingMode,
    Menu, FloatField, BoolField, Action, IPAddressField, TextField,
    MonitoringMode, Page, LogView,
)
from flags import DEVELOPMENT_MODE
from managers.manager_logger import Logger
from controllers.controller_pid import PIDController
from controllers.controller_feedforward import FeedforwardController
from services.service_messageserver import MessageServer
from platform_spec import (
    DEFAULT_OT_MAX_HEATING_SETPOINT, DEFAULT_OT_MANUAL_HEATING_SETPOINT, DEFAULT_OT_DHW_SETPOINT,
    DEFAULT_OT_ENABLE_CONTROLLER, DEFAULT_OT_ENABLE_HEATING, DEFAULT_OT_ENABLE_DHW, DEFAULT_OT_ENFORCE_DHW_SETPOINT,
    DEFAULT_AUTOH_ENABLE, DEFAULT_AUTOH_OFF_TEMP, DEFAULT_AUTOH_OFF_VALVE_LEVEL, DEFAULT_AUTOH_ON_TEMP, DEFAULT_AUTOH_ON_VALVE_LEVEL,
    DEFAULT_PID_KP, DEFAULT_PID_KI, DEFAULT_PID_KD, DEFAULT_PID_SETPOINT, DEFAULT_PID_MIN_HEATING_SETPOINT,
    DEFAULT_PID_VALVE_MIN, DEFAULT_PID_VALVE_MAX, DEFAULT_PID_FF_WIND_COEFF, DEFAULT_PID_FF_TEMP_COEFF,
    DEFAULT_PID_FF_SUN_COEFF, DEFAULT_PID_FF_WIND_CHILL_COEFF, DEFAULT_PID_BASE_TEMP_REF_OUTSIDE,
    DEFAULT_PID_BASE_TEMP_BOILER, DEFAULT_PID_OUTPUT_DEADBAND, DEFAULT_PID_INTEGRAL_ACCUMULATION_RANGE
)

logger = Logger()


# --------------------------------------------------------------------------- #
#  Hardware Initialisation
# --------------------------------------------------------------------------- #

def initialize_hardware(cfg):
    """Initialise I²C bus, peripherals and OpenTherm driver."""
    
    logger.info("Initialising hardware...")
    
    i2c = HWi2c(cfg)
    mcp = HWMCP(i2c, cfg)
    lcd = HWLCD(mcp, cfg)
    display = DisplayController(lcd)
    led = HWRGBLed(mcp, cfg)
    buttons = HWButtons(mcp, cfg)
    
    logger.info("Hardware initialised.")
    
    # Return all initialized hardware components
    return display, led, buttons


# --------------------------------------------------------------------------- #
#  Configuration Loading - Now handled internally by ConfigManager
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
#  GUI Setup
# --------------------------------------------------------------------------- #

def setup_gui(gui, cfg, wifi, hm, ot_manager, pid, heating_controller):
    """Builds the menu structure and sets up GUI modes."""
    logger.info("Setting up GUI...")
    

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
            FloatField("Max Heating SP", cfg.get("OT", "MAX_HEATING_SETPOINT", DEFAULT_OT_MAX_HEATING_SETPOINT), lambda v: cfg.set("OT", "MAX_HEATING_SETPOINT", v)),
            FloatField("Manual Heating SP", cfg.get("OT", "MANUAL_HEATING_SETPOINT", DEFAULT_OT_MANUAL_HEATING_SETPOINT), lambda v: cfg.set("OT", "MANUAL_HEATING_SETPOINT", v)),
            FloatField("DHW Setpoint", cfg.get("OT", "DHW_SETPOINT", DEFAULT_OT_DHW_SETPOINT), lambda v: cfg.set("OT", "DHW_SETPOINT", v)),
            BoolField("Takeover Control", cfg.get("OT", "ENABLE_CONTROLLER", DEFAULT_OT_ENABLE_CONTROLLER), lambda v: cfg.set("OT", "ENABLE_CONTROLLER", v)),
            BoolField("Enable Heating", cfg.get("OT", "ENABLE_HEATING", DEFAULT_OT_ENABLE_HEATING), lambda v: cfg.set("OT", "ENABLE_HEATING", v)),
            BoolField("Enable DHW", cfg.get("OT", "ENABLE_DHW", DEFAULT_OT_ENABLE_DHW), lambda v: cfg.set("OT", "ENABLE_DHW", v)),
            BoolField("Enforce DHW SP", cfg.get("OT", "ENFORCE_DHW_SETPOINT", DEFAULT_OT_ENFORCE_DHW_SETPOINT), lambda v: cfg.set("OT", "ENFORCE_DHW_SETPOINT", v)),
        ]),
        Menu("Auto Heating", [
            Action("Trigger Turn ON", heating_controller.trigger_heating_on),
            Action("Trigger Turn OFF", heating_controller.trigger_heating_off),
            BoolField("Enable Auto", cfg.get("AUTOH", "ENABLE", DEFAULT_AUTOH_ENABLE), lambda v: cfg.set("AUTOH", "ENABLE", v)),
            FloatField("Off Temp >=", cfg.get("AUTOH", "OFF_TEMP", DEFAULT_AUTOH_OFF_TEMP), lambda v: cfg.set("AUTOH", "OFF_TEMP", v)),
            FloatField("Off Valve <", cfg.get("AUTOH", "OFF_VALVE_LEVEL", DEFAULT_AUTOH_OFF_VALVE_LEVEL), lambda v: cfg.set("AUTOH", "OFF_VALVE_LEVEL", v)),
            FloatField("On Temp <", cfg.get("AUTOH", "ON_TEMP", DEFAULT_AUTOH_ON_TEMP), lambda v: cfg.set("AUTOH", "ON_TEMP", v)),
            FloatField("On Valve >", cfg.get("AUTOH", "ON_VALVE_LEVEL", DEFAULT_AUTOH_ON_VALVE_LEVEL), lambda v: cfg.set("AUTOH", "ON_VALVE_LEVEL", v)),
        ]),
        Menu("PID", [
            Action("Reset PID state", pid.reset),
            FloatField("Prop. Gain (Kp)", cfg.get("PID", "KP", DEFAULT_PID_KP), 
                       lambda v: cfg.set("PID", "KP", v), 
                       precision=5), 
            FloatField("Integ. Gain (Ki)", cfg.get("PID", "KI", DEFAULT_PID_KI), 
                       lambda v: cfg.set("PID", "KI", v), 
                       precision=5),
            FloatField("Deriv. Gain (Kd)", cfg.get("PID", "KD", DEFAULT_PID_KD), 
                       lambda v: cfg.set("PID", "KD", v), 
                       precision=5),
            FloatField("Integral Range", cfg.get("PID", "INTEGRAL_ACCUMULATION_RANGE", DEFAULT_PID_INTEGRAL_ACCUMULATION_RANGE), 
                       lambda v: cfg.set("PID", "INTEGRAL_ACCUMULATION_RANGE", v),
                       precision=2),
            FloatField("Setpoint (Valve%)", cfg.get("PID", "SETPOINT", DEFAULT_PID_SETPOINT), 
                       lambda v: cfg.set("PID", "SETPOINT", v)),
            FloatField("Valve Min %", cfg.get("PID", "VALVE_MIN", DEFAULT_PID_VALVE_MIN), 
                       lambda v: cfg.set("PID", "VALVE_MIN", v)),
            FloatField("Valve Max %", cfg.get("PID", "VALVE_MAX", DEFAULT_PID_VALVE_MAX), 
                       lambda v: cfg.set("PID", "VALVE_MAX", v)),
            FloatField("Output Deadband", cfg.get("PID", "OUTPUT_DEADBAND", DEFAULT_PID_OUTPUT_DEADBAND), 
                       lambda v: cfg.set("PID", "OUTPUT_DEADBAND", v)),
        ]),
        Menu("Feedforward", [
            FloatField("Wind Coeff", cfg.get("FEEDFORWARD", "WIND_COEFF", DEFAULT_PID_FF_WIND_COEFF), 
                       lambda v: cfg.set("FEEDFORWARD", "WIND_COEFF", v)),
            FloatField("Temp Coeff", cfg.get("FEEDFORWARD", "TEMP_COEFF", DEFAULT_PID_FF_TEMP_COEFF), 
                       lambda v: cfg.set("FEEDFORWARD", "TEMP_COEFF", v)),
            FloatField("Sun Coeff", cfg.get("FEEDFORWARD", "SUN_COEFF", DEFAULT_PID_FF_SUN_COEFF), 
                       lambda v: cfg.set("FEEDFORWARD", "SUN_COEFF", v)),
            FloatField("Wind Interact", cfg.get("FEEDFORWARD", "WIND_CHILL_COEFF", DEFAULT_PID_FF_WIND_CHILL_COEFF), 
                       lambda v: cfg.set("FEEDFORWARD", "WIND_CHILL_COEFF", v), 
                       precision=4),
            FloatField("Base Temp Outside", cfg.get("FEEDFORWARD", "BASE_TEMP_REF_OUTSIDE", DEFAULT_PID_BASE_TEMP_REF_OUTSIDE), 
                       lambda v: cfg.set("FEEDFORWARD", "BASE_TEMP_REF_OUTSIDE", v)),
            FloatField("Base Temp Boiler", cfg.get("FEEDFORWARD", "BASE_TEMP_BOILER", DEFAULT_PID_BASE_TEMP_BOILER), 
                       lambda v: cfg.set("FEEDFORWARD", "BASE_TEMP_BOILER", v)),
        ]),
        Menu("Device", [
            Action("View Log", lambda: gui.switch_mode("logview")),
            Action("Reset Error limiter", logger.reset_error_rate_limiter),
            Action("Reboot Device", reset),
            Action("Factory defaults", lambda: factory_reset(gui.display, gui.led)),
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
    mon.add_page(Page(lambda: (f"Avg :{hm.avg_valve:.1f}%" if hm.is_ccu_connected() else "Valve Status"),
                       lambda: (f"AvgAct:{hm.avg_active_valve:.1f}% {hm.reporting_valves}" if hm.is_ccu_connected() else "CCU Offline")))
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
    # Page 8: OpenTherm Fault Status
    mon.add_page(Page(lambda: f"Fault: {ot_manager.is_fault_present()}",
                       lambda: f"Flags: {ot_manager.get_fault_flags()}")) # Assumes get_fault_flags returns a printable value

    gui.add_mode("monitoring", mon)

    log_view = LogView("log.txt", gui.display.rows, gui.display.cols)
    gui.add_mode("logview", log_view)

    gui.switch_mode("monitoring")
    logger.info("GUI setup complete.")


# --------------------------------------------------------------------------- #
#  Service Initialisation
# --------------------------------------------------------------------------- #

def initialize_services(cfg):
    """Initialises services using the provided configuration manager."""
    logger.info("Initialising services...")
    
    # --- Instantiate Core Services ---
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
        weather_device_type=str(cfg.get("CCU3", "WEATHER_DEVTYPE", "HmIP-SWO"))
    )
    
    # --- Instantiate OpenTherm Manager ---
    logger.info("Initialising OpenTherm Manager...")
    uart = HWUART(cfg)
    ot_controller = OpenThermController(uart)
    opentherm = OpenThermManager(ot_controller)
    logger.info("OpenTherm Manager initialised.")

    # --- Instantiate Message Server ---
    message_server = MessageServer(port=23) 
    logger.set_message_server(message_server)

    # --- Instantiate PID Controller ---
    logger.info("Instantiating PID Controller...")
    pid = PIDController(
        kp=cfg.get("PID", "KP", DEFAULT_PID_KP), 
        ki=cfg.get("PID", "KI", DEFAULT_PID_KI),
        kd=cfg.get("PID", "KD", DEFAULT_PID_KD),
        setpoint=cfg.get("PID", "SETPOINT", DEFAULT_PID_SETPOINT),
        output_min=cfg.get("PID", "MIN_HEATING_SETPOINT", DEFAULT_PID_MIN_HEATING_SETPOINT),
        output_max=cfg.get("OT", "MAX_HEATING_SETPOINT", DEFAULT_OT_MAX_HEATING_SETPOINT),
        integral_accumulation_range=cfg.get("PID", "INTEGRAL_ACCUMULATION_RANGE", DEFAULT_PID_INTEGRAL_ACCUMULATION_RANGE),
        valve_input_min=cfg.get("PID", "VALVE_MIN", DEFAULT_PID_VALVE_MIN),
        valve_input_max=cfg.get("PID", "VALVE_MAX", DEFAULT_PID_VALVE_MAX),
        time_factor=1.0,
        output_deadband=cfg.get("PID", "OUTPUT_DEADBAND", DEFAULT_PID_OUTPUT_DEADBAND)
    )
    logger.info("PID Controller instantiated.")

    # --- Instantiate Feedforward Controller ---
    logger.info("Instantiating Feedforward Controller...")
    feedforward = FeedforwardController(
        wind_coeff=cfg.get("FEEDFORWARD", "WIND_COEFF", DEFAULT_PID_FF_WIND_COEFF),
        temp_coeff=cfg.get("FEEDFORWARD", "TEMP_COEFF", DEFAULT_PID_FF_TEMP_COEFF),
        sun_coeff=cfg.get("FEEDFORWARD", "SUN_COEFF", DEFAULT_PID_FF_SUN_COEFF),
        wind_chill_coeff=cfg.get("FEEDFORWARD", "WIND_CHILL_COEFF", DEFAULT_PID_FF_WIND_CHILL_COEFF),
        base_temp_ref_outside=cfg.get("FEEDFORWARD", "BASE_TEMP_REF_OUTSIDE", DEFAULT_PID_BASE_TEMP_REF_OUTSIDE),
        base_temp_boiler=cfg.get("FEEDFORWARD", "BASE_TEMP_BOILER", DEFAULT_PID_BASE_TEMP_BOILER)
    )
    logger.info("Feedforward Controller instantiated.")

    # --- Instantiate Heating Controller ---
    logger.info("Instantiating Heating Controller...")
    heating_controller = HeatingController(
        cfg,
        cfg.get("PID", "MIN_HEATING_SETPOINT", DEFAULT_PID_MIN_HEATING_SETPOINT),
        cfg.get("OT", "MAX_HEATING_SETPOINT", DEFAULT_OT_MAX_HEATING_SETPOINT),
        hm, 
        opentherm, 
        pid, 
        feedforward
    )
    logger.info("Heating Controller instantiated.")

    logger.info("Services initialised.")
    # Return manager and services, NO LONGER RETURNING cfg
    return wifi, hm, pid, message_server, heating_controller
