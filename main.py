"""
main.py


"""

# --------------------------------------------------------------------------- #
#  Imports
# --------------------------------------------------------------------------- #
import utime as time
import uasyncio as asyncio
import uos

from machine import reset

# 3rd‑party / project modules
from hardware_config import (
    init_i2c, init_mcp, init_lcd, init_rgb_led, init_buttons,
    unique_hardware_name, CUSTOM_CHARS,
)
from controllers.controller_display import DisplayController
from controllers.controller_HID import HIDController
from controllers.controller_otgw import OpenThermController
from managers.manager_otgw import OpenThermManager
from gui import (
    GUIManager, NavigationMode, EditingMode,
    Menu, FloatField, BoolField, Action, IPAddressField, TextField,
    MonitoringMode, Page, LogView,
)
from managers.manager_config import ConfigManager, factory_reset
from managers.manager_logger import Logger
from managers.manager_wifi import WiFiManager
from services.service_homematic_rpc import HomematicDataService

DEVELOPMENT_MODE=1
error_manager = Logger()
DEBUG = error_manager.get_level()
# --------------------------------------------------------------------------- #
#  Globals & runtime state
# --------------------------------------------------------------------------- #
# error_manager = ErrorManager()
# global error_manager

class RuntimeState:
    """Mutable container for runtime flags."""

    def __init__(self):
        pass  # No longer storing OT state here


STATE = RuntimeState()

# Placeholder PID constants used by one of the monitoring pages
Kp, Ki, Kd, OUT = 0.0, 0.0, 0.0, 54.0


# --------------------------------------------------------------------------- #
#  Initialisation helpers
# --------------------------------------------------------------------------- #

def init_hardware():
    """Initialise I²C bus, peripherals and OpenTherm driver."""
    i2c = init_i2c()
    mcp = init_mcp(i2c)
    display = DisplayController(init_lcd(mcp))
    led = init_rgb_led(mcp)
    buttons = init_buttons(mcp)

    return display, led, buttons


def load_config(path: str = "config.txt"):
    """Return `(config_manager, cfg_values_dict)` from *path*."""
    cfg_mgr = ConfigManager(path)

    def _bool(section, key, default=False):
        # --- Debugging ---
        raw_value = cfg_mgr.get_value(section, key, default)
        error_manager.info(f"DEBUG _bool: Section='{section}', Key='{key}', RawValue='{raw_value}' (Type: {type(raw_value)})")
        # --- End Debugging ---

        # Get value, strip whitespace, convert to lower, then compare
        value_str = str(raw_value).strip().lower()
        result = value_str == "true"

        # --- Debugging ---
        error_manager.info(f"DEBUG _bool: Processed Value='{value_str}', Result={result}")
        # --- End Debugging ---
        return result

    cfg = {
        "debug": cfg_mgr.get_value("DEVICE","DEBUG",1),
        # Wi‑Fi
        "ssid": cfg_mgr.get_value("WIFI", "SSID"),
        "wifi_pass": cfg_mgr.get_value("WIFI", "PASS"),
        # Homematic
        "ccu_ip": cfg_mgr.get_value("CCU3", "IP", "0.0.0.0"),
        "ccu_user": cfg_mgr.get_value("CCU3", "USER", ""),
        "ccu_pass": cfg_mgr.get_value("CCU3", "PASS", ""),
        "valve_type": cfg_mgr.get_value("CCU3", "VALVE_DEVTYPE", "HmIP-eTRV"),
        # OpenTherm
        "ot_max_heating_setpoint": float(cfg_mgr.get_value("OT", "MAX_HEATING_SETPOINT", 72.0)),
        "ot_manual_heating_setpoint": float(cfg_mgr.get_value("OT", "MANUAL_HEATING_SETPOINT", 55.0)),
        "ot_dhw_setpoint": float(cfg_mgr.get_value("OT", "DHW_SETPOINT", 50.0)),
        "ot_manual_heating": _bool("OT", "MANUAL_HEATING"),
        "ot_enable_controller": _bool("OT", "ENABLE_CONTROLLER"),
        "ot_enable_heating": _bool("OT", "ENABLE_HEATING"),
        "ot_enable_dhw": _bool("OT", "ENABLE_DHW"),
        # MQTT
        "mqtt_broker": cfg_mgr.get_value("MQTT", "BROKER"),
        "mqtt_port": int(cfg_mgr.get_value("MQTT", "PORT", 1883)),
        "mqtt_user": cfg_mgr.get_value("MQTT", "USER", ""),
        "mqtt_pass": cfg_mgr.get_value("MQTT", "PASS", ""),
        "mqtt_base_topic": cfg_mgr.get_value("MQTT", "BASE_TOPIC", "home/ot-controller"),
    }

    return cfg_mgr, cfg


# --------------------------------------------------------------------------- #
#  Fatal‑error handler
# --------------------------------------------------------------------------- #

def handle_fatal_error(err_type, display, led, msg, tb=None):
    error_manager.fatal(err_type, msg, tb)
    try:
        if display:
            display.show_message("FATAL ERROR", "REBOOTING..." if not DEVELOPMENT_MODE else "ERROR")
        if led:
            led.direct_send_color("red")
    except Exception as disp_exc:  # noqa: BLE001
        error_manager.error(f"Display fail in fatal handler: {disp_exc}")

    time.sleep(2)
    if DEVELOPMENT_MODE:
        error_manager.error(f"[DEV] FATAL {err_type}: {msg}\n{tb}")
        while True:
            time.sleep(1)
    else:
        reset()


# --------------------------------------------------------------------------- #
#  Asynchronous tasks
# --------------------------------------------------------------------------- #

async def wifi_task(wifi):
    while True:
        try:
            wifi.update()
        except Exception as e:  # noqa: BLE001
            error_manager.error(f"WiFi: {e}")
        await asyncio.sleep(5)


async def led_task(led):
    while True:
        try:
            led.update()
        except Exception as e:  # noqa: BLE001
            error_manager.error(f"LED: {e}")
        await asyncio.sleep_ms(100)


async def homematic_task(hm):
    while True:
        try:
            hm.update()
        except Exception as e:  # noqa: BLE001
            error_manager.error(f"HM: {e}")
        await asyncio.sleep(5)


async def poll_buttons_task(hid):
    while True:
        hid.get_event()
        await asyncio.sleep_ms(20)


async def error_rate_limiter_task(hm, wifi, led):
    """Watch the `ErrorManager` limiter flag and perform a quick reset cycle."""
    while True:
        if error_manager.error_rate_limiter_reached:
            error_manager.warning("Error‑rate limiter TRIGGERED – running cooldown cycle")
            try:
                hm.set_paused(True)
                wifi.disconnect()
                led.set_color("red", blink=False)
            except Exception as e:  # noqa: BLE001
                error_manager.error(f"Limiter prep: {e}")

            error_manager.reset_error_rate_limiter()

            try:
                hm.set_paused(False)
                wifi.update()
            except Exception as e:  # noqa: BLE001
                error_manager.error(f"Limiter resume: {e}")
        await asyncio.sleep(1)


async def main_status_task(hm, wifi, led):
    while True:
        if wifi.is_connected():
            hm.set_paused(False)
            led.set_color("green" if hm.is_ccu_connected() else "magenta",
                           blink=True, duration_on=50, duration_off=2000)
        else:
            hm.set_paused(True)
            led.set_color("red", blink=True, duration_on=1000, duration_off=1000)

        # Controller state is now self-managed, no need to update from STATE
        await asyncio.sleep(1)


# --------------------------------------------------------------------------- #
#  Menu construction
# --------------------------------------------------------------------------- #

def build_menu(cfg_mgr, cfg, wifi, hm, gui_mgr, ot_manager):
    def save(sec, key, val):
        cfg_mgr.set_value(sec, key, val)
        cfg_mgr.save_config()

        # Note: These manager calls might be async internally but return bool here.
        # We don't need create_task as the manager handles the async execution.
        if sec == "OT":
            if key == "ENABLE_CONTROLLER":
                 # Call directly, manager handles async internally
                 ot_manager.take_control() if val else ot_manager.relinquish_control()
            elif key == "ENABLE_HEATING":
                 ot_manager.set_central_heating(val)
            elif key == "ENABLE_DHW":
                 # Convert bool to 1/0 for manager method
                 ot_manager.set_hot_water_mode(1 if val else 0)
            elif key == "MANUAL_HEATING_SETPOINT": # Maps to Control Setpoint (CS)
                ot_manager.set_control_setpoint(val)
            elif key == "DHW_SETPOINT":
                ot_manager.set_dhw_setpoint(val)
            elif key == "MAX_HEATING_SETPOINT":
                ot_manager.set_max_ch_setpoint(val)

    def save_and_reboot():
        gui_mgr.display.show_message("Action", "Saving & Reboot")
        cfg_mgr.save_config()
        time.sleep(1)
        reset()

    items = [
        Menu("Network", [
            TextField("WiFi SSID", cfg["ssid"], lambda v: save("WIFI", "SSID", v)),
            TextField("WiFi Pass", cfg["wifi_pass"], lambda v: save("WIFI", "PASS", v)),
        ]),
        Menu("Homematic", [
            IPAddressField("CCU3 IP", cfg["ccu_ip"], lambda v: save("CCU3", "IP", v)),
            TextField("CCU3 User", cfg["ccu_user"], lambda v: save("CCU3", "USER", v)),
            TextField("CCU3 Pass", cfg["ccu_pass"], lambda v: save("CCU3", "PASS", v)),
            TextField("Valve Type", cfg["valve_type"], lambda v: save("CCU3", "VALVE_DEVTYPE", v)),
            Action("Rescan", hm.force_rescan),
        ]),
        Menu("OpenTherm", [
            FloatField("Max Heating SP", cfg.get("ot_max_heating_setpoint", 0.0), lambda v: save("OT", "MAX_HEATING_SETPOINT", v)),
            FloatField("Control Setpoint", cfg.get("ot_manual_heating_setpoint", 0.0), lambda v: save("OT", "MANUAL_HEATING_SETPOINT", v)),
            FloatField("DHW Setpoint", cfg.get("ot_dhw_setpoint", 0.0), lambda v: save("OT", "DHW_SETPOINT", v)),
            BoolField("Takeover Control", cfg.get("ot_enable_controller", False), lambda v: save("OT", "ENABLE_CONTROLLER", v)),
            BoolField("Enable Heating", cfg.get("ot_enable_heating", False), lambda v: save("OT", "ENABLE_HEATING", v)),
            BoolField("Enable DHW", cfg.get("ot_enable_dhw", False), lambda v: save("OT", "ENABLE_DHW", v)),
        ]),
        Menu("Device", [
            Action("View Log", lambda: gui_mgr.switch_mode("logview")),
            Action("Reset Error limiter", error_manager.reset_error_rate_limiter),
            Action("Reboot Device", reset),
            Action("Save & Reboot", save_and_reboot),
            Action("Factory defaults", lambda: factory_reset(gui_mgr.display, gui_mgr.led, cfg_mgr, hm)),
        ]),
    ]

    if DEVELOPMENT_MODE:
        items.append(Menu("Debug", [
            Action("Force wifi disconnect", wifi.disconnect),
            Action("Fake Error", lambda: error_manager.error("Fake Error")),
        ]))

    return Menu("Main Menu", items)


# --------------------------------------------------------------------------- #
#  Background task registration
# --------------------------------------------------------------------------- #

def schedule_tasks(loop, *, wifi, hm, led, ot_manager, hid):
    for coro in (
        wifi_task(wifi), led_task(led), homematic_task(hm),
        poll_buttons_task(hid), main_status_task(hm, wifi, led),
        error_rate_limiter_task(hm, wifi, led),
    ):
        loop.create_task(coro)


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #

def main():  # noqa: C901
    # -------------------------------- Hardware & services ------------------- #
    try:
        display, led, buttons = init_hardware()
    except Exception as e:  # noqa: BLE001
        handle_fatal_error("Hardware", None, None, str(e))
        return

    try:
        cfg_mgr, cfg = load_config()
        error_manager.info(f"DEBUG: {DEBUG}")
        wifi = WiFiManager(cfg["ssid"], cfg["wifi_pass"], unique_hardware_name()[:15])
        hm = HomematicDataService(
            f"http://{cfg['ccu_ip']}/api/homematic.cgi",
            cfg["ccu_user"], cfg["ccu_pass"], cfg["valve_type"],
        )
        ot_controller = OpenThermController(error_manager)
        ot_manager = OpenThermManager(ot_controller, error_manager)

        base = cfg["mqtt_base_topic"]

    except Exception as e:  # noqa: BLE001
        handle_fatal_error("ServiceInit", display, led, str(e))
        return

    # -------------------------------- GUI ----------------------------------- #
    try:
        gui = GUIManager(display, buttons)
        # Build menu with the new OpenTherm manager
        root_menu = build_menu(cfg_mgr, cfg, wifi, hm, gui, ot_manager)
        gui.add_mode("navigation", NavigationMode(root_menu))
        gui.add_mode("editing", EditingMode())

        mon = MonitoringMode(refresh_interval_ms=250)
        # Page 1: Network / CCU status (kept from clean version)
        mon.add_page(Page(lambda: f"Net: {wifi.get_ip() or 'NA'}",
                           lambda: f"CCU: {hm.is_ccu_connected()}"))
        # Page 2: Valve status
        mon.add_page(Page(lambda: (f"Avg: {hm.avg_valve:.1f}%" if hm.is_ccu_connected() else "Valve Status"),
                           lambda: (f"Max: {hm.max_valve:.1f}% {hm.valve_devices}/{hm.reporting_valves}" if hm.is_ccu_connected() else "CCU Offline")))
        # Page 3: PID constants
        mon.add_page(Page(lambda: f"Kp: {Kp:.2f} Ki: {Ki:.2f}",
                           lambda: f"Kd: {Kd:.2f} OUT: {OUT:.2f}"))
        # Page 4: Setpoints (using manager getters)
        mon.add_page(Page(lambda: f"DHW SP: {ot_manager.get_dhw_setpoint()}",
                           lambda: f"Control SP: {ot_manager.get_control_setpoint()}"))
        # Page 5: Current OT set‑points (using manager getters)
        mon.add_page(Page(lambda: f"Heating SP: {ot_manager.get_control_setpoint()}",
                           lambda: f"DHW SP: {ot_manager.get_dhw_setpoint()}"))
        # Page 6: OT controller status (using manager getters)
        mon.add_page(Page(lambda: f"OT State: {'On' if ot_manager.is_active() else 'Off'}",
                           lambda: f"Heat: {'On' if ot_manager.is_ch_enabled() else 'Off'} DHW: {'On' if ot_manager.is_dhw_enabled() else 'Off'}"))
        # Page 7: Room with max valve opening
        mon.add_page(Page(lambda: f"Room: {hm.max_valve_room_name}",
                           lambda: f"Max Valve: {hm.max_valve:.1f}%" if hm.is_ccu_connected() else "(CCU Offline)"))

        gui.add_mode("monitoring", mon)

        log_view = LogView("log.txt", display.rows, display.cols)
        gui.add_mode("logview", log_view)

        gui.switch_mode("monitoring")

    except Exception as e:  # noqa: BLE001
            handle_fatal_error("GUIInit", display, led, str(e))
            return

    loop = asyncio.get_event_loop()
    schedule_tasks(loop, wifi=wifi, hm=hm, led=led, ot_manager=ot_manager, hid=buttons)

    try:
        error_manager.info("Starting OpenTherm Manager...")
        loop.run_until_complete(ot_manager.start())
        error_manager.info("OpenTherm Manager started. Setting initial state from config...")

        # Set initial state using manager methods after start()
        # These methods launch background tasks internally if needed
        if "ot_max_heating_setpoint" in cfg:
             ot_manager.set_max_ch_setpoint(cfg["ot_max_heating_setpoint"])
        if "ot_dhw_setpoint" in cfg:
             ot_manager.set_dhw_setpoint(cfg["ot_dhw_setpoint"])
        if "ot_manual_heating_setpoint" in cfg: # Maps to Control Setpoint
             ot_manager.set_control_setpoint(cfg["ot_manual_heating_setpoint"])
        # Set initial enabled states
        if cfg.get("ot_enable_heating"):
             ot_manager.set_central_heating(True)
        if cfg.get("ot_enable_dhw"):
             ot_manager.set_hot_water_mode(1) # Enable DHW mode
        # Set initial controller state (takeover)
        if cfg.get("ot_enable_controller"):
             # Pass the configured Control Setpoint as the initial setpoint for takeover
             initial_cs = cfg.get("ot_manual_heating_setpoint", 45.0) # Default to 45 if not in config
             ot_manager.take_control(initial_setpoint=initial_cs)

        error_manager.info("Initial state set commands issued.")

    except Exception as e:
        handle_fatal_error("ManagerStart", display, led, str(e))
        return

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        error_manager.error("KeyboardInterrupt  shutdown")
    finally:
        display.clear()
        error_manager.info("Stopping OpenTherm Manager...")
        loop = asyncio.get_event_loop()
        loop.run_until_complete(ot_manager.stop())
        error_manager.info("OpenTherm Manager stopped.")
        led.direct_send_color("red")
        asyncio.new_event_loop()


if __name__ == "__main__":
    main()
