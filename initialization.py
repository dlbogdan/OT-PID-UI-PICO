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
#  Configuration Loading
# --------------------------------------------------------------------------- #

def load_config(cfg_mgr):
    """Load configuration values from the ConfigManager."""
    logger.info("Loading configuration...")

    def _bool(section, key, default=False):
        raw_value = cfg_mgr.get_value(section, key, default)
        # logger.info(f"DEBUG _bool: Section='{section}', Key='{key}', RawValue='{raw_value}' (Type: {type(raw_value)})") # Keep commented unless debugging
        value_str = str(raw_value).strip().lower()
        result = value_str == "true"
        # logger.info(f"DEBUG _bool: Processed Value='{value_str}', Result={result}") # Keep commented unless debugging
        return result

    cfg = {
        "debug": cfg_mgr.get_value("DEVICE", "DEBUG", 1),
        # Wi‑Fi
        "ssid": cfg_mgr.get_value("WIFI", "SSID"),
        "wifi_pass": cfg_mgr.get_value("WIFI", "PASS"),
        # Homematic
        "ccu_ip": cfg_mgr.get_value("CCU3", "IP", "0.0.0.0"),
        "ccu_user": cfg_mgr.get_value("CCU3", "USER", ""),
        "ccu_pass": cfg_mgr.get_value("CCU3", "PASS", ""),
        "valve_type": cfg_mgr.get_value("CCU3", "VALVE_DEVTYPE", "HmIP-eTRV"),
        "weather_type": cfg_mgr.get_value("CCU3", "WEATHER_DEVTYPE", "HmIP-SWO"),
        # OpenTherm
        "ot_max_heating_setpoint": float(cfg_mgr.get_value("OT", "MAX_HEATING_SETPOINT", 72.0)),
        "ot_manual_heating_setpoint": float(cfg_mgr.get_value("OT", "MANUAL_HEATING_SETPOINT", 55.0)),
        "ot_dhw_setpoint": float(cfg_mgr.get_value("OT", "DHW_SETPOINT", 50.0)),
        "ot_manual_heating": _bool("OT", "MANUAL_HEATING"), # Note: This seems unused after loading? Check usage.
        "ot_enable_controller": _bool("OT", "ENABLE_CONTROLLER"),
        "ot_enable_heating": _bool("OT", "ENABLE_HEATING"),
        "ot_enable_dhw": _bool("OT", "ENABLE_DHW"),
        # MQTT (Keep even if unused for now, might be needed later)
        "mqtt_broker": cfg_mgr.get_value("MQTT", "BROKER"),
        "mqtt_port": int(cfg_mgr.get_value("MQTT", "PORT", 1883)),
        "mqtt_user": cfg_mgr.get_value("MQTT", "USER", ""),
        "mqtt_pass": cfg_mgr.get_value("MQTT", "PASS", ""),
        "mqtt_base_topic": cfg_mgr.get_value("MQTT", "BASE_TOPIC", "home/ot-controller"),
        # PID Controller
        "pid_kp": float(cfg_mgr.get_value("PID", "KP", 0.05)),
        "pid_ki": float(cfg_mgr.get_value("PID", "KI", 0.002)),
        "pid_kd": float(cfg_mgr.get_value("PID", "KD", 0.01)),
        "pid_setpoint": float(cfg_mgr.get_value("PID", "SETPOINT", 25.0)),
        "pid_interval_s": int(cfg_mgr.get_value("PID", "UPDATE_INTERVAL_SEC", 30)),
        "pid_valve_min": float(cfg_mgr.get_value("PID", "VALVE_MIN", 8.0)),
        "pid_valve_max": float(cfg_mgr.get_value("PID", "VALVE_MAX", 70.0)),
        "pid_ff_wind": float(cfg_mgr.get_value("PID", "FF_WIND_COEFF", 0.1)),
        "pid_ff_wind_interact": float(cfg_mgr.get_value("PID", "FF_WIND_INTERACTION_COEFF", 0.008)),
        "pid_ff_temp": float(cfg_mgr.get_value("PID", "FF_TEMP_COEFF", 1.1)),
        "pid_ff_sun": float(cfg_mgr.get_value("PID", "FF_SUN_COEFF", 0.0001)),
        "pid_base_temp_ref": float(cfg_mgr.get_value("PID", "BASE_TEMP_REF_OUTSIDE", 10.0)),
        "pid_base_temp_boiler": float(cfg_mgr.get_value("PID", "BASE_TEMP_BOILER", 45.0)),
    }
    logger.info("Configuration loaded.")
    return cfg


# --------------------------------------------------------------------------- #
#  GUI Setup
# --------------------------------------------------------------------------- #

def setup_gui(gui, cfg_mgr, cfg, wifi, hm, ot_manager):
    """Builds the menu structure and sets up GUI modes."""
    logger.info("Setting up GUI...")

    # Define save callback here as it needs cfg_mgr and potentially ot_manager
    def save(sec, key, val):
        logger.info(f"Saving config: Section={sec}, Key={key}, Value={val}")
        cfg_mgr.set_value(sec, key, val)
        cfg_mgr.save_config()
        logger.info("Config saved.")

        # Update runtime state via managers
        if sec == "OT":
            try:
                if key == "ENABLE_CONTROLLER":
                     ot_manager.take_control() if val else ot_manager.relinquish_control()
                elif key == "ENABLE_HEATING":
                     ot_manager.set_central_heating(val)
                elif key == "ENABLE_DHW":
                     ot_manager.set_hot_water_mode(1 if val else 0)
                elif key == "MANUAL_HEATING_SETPOINT":
                    ot_manager.set_control_setpoint(float(val))
                elif key == "DHW_SETPOINT":
                    ot_manager.set_dhw_setpoint(float(val))
                elif key == "MAX_HEATING_SETPOINT":
                    ot_manager.set_max_ch_setpoint(float(val))
                logger.info(f"OT state update for {key} applied.")
            except Exception as e:
                logger.error(f"Failed to apply OT setting {key}={val}: {e}")

    def save_and_reboot():
        gui.display.show_message("Action", "Saving & Reboot")
        try:
            cfg_mgr.save_config()
            logger.info("Config saved before reboot.")
        except Exception as e:
            logger.error(f"Failed to save config before reboot: {e}")
        time.sleep(1)
        reset()

    # --- Build Menu Structure --- # 
    menu_items = [
        Menu("Network", [
            TextField("WiFi SSID", cfg["ssid"], lambda v: save("WIFI", "SSID", v)),
            TextField("WiFi Pass", cfg["wifi_pass"], lambda v: save("WIFI", "PASS", v)),
        ]),
        Menu("Homematic", [
            IPAddressField("CCU3 IP", cfg["ccu_ip"], lambda v: save("CCU3", "IP", v)),
            TextField("CCU3 User", cfg["ccu_user"], lambda v: save("CCU3", "USER", v)),
            TextField("CCU3 Pass", cfg["ccu_pass"], lambda v: save("CCU3", "PASS", v)),
            TextField("Valve Type", cfg["valve_type"], lambda v: save("CCU3", "VALVE_DEVTYPE", v)),
            TextField("Weather Type", cfg["weather_type"], lambda v: save("CCU3", "WEATHER_DEVTYPE", v)),
            Action("Rescan", hm.force_rescan), # Assuming hm has force_rescan
        ]),
        Menu("OpenTherm", [
            # Use .get() with defaults for robustness
            FloatField("Max Heating SP", cfg.get("ot_max_heating_setpoint", 72.0), lambda v: save("OT", "MAX_HEATING_SETPOINT", v)),
            FloatField("Control Setpoint", cfg.get("ot_manual_heating_setpoint", 55.0), lambda v: save("OT", "MANUAL_HEATING_SETPOINT", v)),
            FloatField("DHW Setpoint", cfg.get("ot_dhw_setpoint", 50.0), lambda v: save("OT", "DHW_SETPOINT", v)),
            BoolField("Takeover Control", cfg.get("ot_enable_controller", False), lambda v: save("OT", "ENABLE_CONTROLLER", v)),
            BoolField("Enable Heating", cfg.get("ot_enable_heating", False), lambda v: save("OT", "ENABLE_HEATING", v)),
            BoolField("Enable DHW", cfg.get("ot_enable_dhw", False), lambda v: save("OT", "ENABLE_DHW", v)),
        ]),
        Menu("Device", [
            Action("View Log", lambda: gui.switch_mode("logview")),
            Action("Reset Error limiter", logger.reset_error_rate_limiter),
            Action("Reboot Device", reset),
            Action("Save & Reboot", save_and_reboot),
            Action("Factory defaults", lambda: factory_reset(gui.display, gui.led, cfg_mgr, hm)), # Pass necessary args
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
                       lambda: f"Heat: {'On' if ot_manager.is_ch_enabled() else 'Off'} DHW: {'On' if ot_manager.is_dhw_enabled() else 'Off'}"))
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
    cfg = load_config(cfg_mgr) # Use the function defined above

    wifi = WiFiManager(cfg["ssid"], cfg["wifi_pass"], unique_hardware_name()[:15])
    hm = HomematicDataService(
        f"http://{cfg['ccu_ip']}/api/homematic.cgi",
        cfg["ccu_user"], cfg["ccu_pass"], cfg["valve_type"],
        weather_device_type=cfg["weather_type"]
    )

    logger.info("Services initialised.")
    # Return managers, config, and services
    return cfg_mgr, cfg, wifi, hm
