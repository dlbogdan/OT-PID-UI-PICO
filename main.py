"""
main.py - cleaned, with monitoring pages & error-rate-limiter task restored

Changelog vs previous clean version
----------------------------------
* Re-added the Valve / PID / OT set-point & room pages to `MonitoringMode`.
* Restored `error_rate_limiter_task` so bursts of errors trigger the short reset
  cycle as before.
* Brought back placeholder PID constants (`Kp`, `Ki`, `Kd`, `OUT`).
* `schedule_tasks()` now registers the new limiter-watch task.

Everything else remains modularised.
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
from controller_display import DisplayController
from controller_HID import HIDController
from drivers.driver_opentherm import OpenthermUARTDriver, OpenthermController
from gui import (
    GUIManager, NavigationMode, EditingMode,
    Menu, FloatField, BoolField, Action, IPAddressField, TextField,
    MonitoringMode, Page, LogView,
)
from manager_config import ConfigManager, factory_reset
from manager_error import ErrorManager
from manager_wifi import WiFiManager
from service_homematic_rpc import HomematicDataService

DEVELOPMENT_MODE=1
error_manager = ErrorManager()
DEBUG = error_manager.get_debuglevel()
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

    ot_driver = OpenthermUARTDriver(10_000)
    ot_driver.start_periodic_update()

    return display, led, buttons, ot_driver


def load_config(path: str = "config.txt"):
    """Return `(config_manager, cfg_values_dict)` from *path*."""
    cfg_mgr = ConfigManager(path)

    def _bool(section, key, default=False):
        return str(cfg_mgr.get_value(section, key, default)).lower() == "true"

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
    error_manager.log_fatal_error(err_type, msg, tb)
    try:
        if display:
            display.show_message("FATAL ERROR", "REBOOTING..." if not DEVELOPMENT_MODE else "ERROR")
        if led:
            led.direct_send_color("red")
    except Exception as disp_exc:  # noqa: BLE001
        error_manager.log_error(f"Display fail in fatal handler: {disp_exc}")

    time.sleep(2)
    if DEVELOPMENT_MODE:
        print(f"[DEV] FATAL {err_type}: {msg}\n{tb}")
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
            error_manager.log_error(f"WiFi: {e}")
        await asyncio.sleep(5)


async def led_task(led):
    while True:
        try:
            led.update()
        except Exception as e:  # noqa: BLE001
            error_manager.log_error(f"LED: {e}")
        await asyncio.sleep_ms(100)


async def homematic_task(hm):
    while True:
        try:
            hm.update()
        except Exception as e:  # noqa: BLE001
            error_manager.log_error(f"HM: {e}")
        await asyncio.sleep(5)


async def opentherm_task(ctl):
    while True:
        try:
            await ctl.update()
        except Exception as e:  # noqa: BLE001
            error_manager.log_error(f"OT: {e}")
            await asyncio.sleep(5)
        await asyncio.sleep_ms(100)


async def poll_buttons_task(hid):
    while True:
        hid.get_event()
        await asyncio.sleep_ms(20)


async def error_rate_limiter_task(hm, wifi, led):
    """Watch the `ErrorManager` limiter flag and perform a quick reset cycle."""
    while True:
        if error_manager.error_rate_limiter_reached:
            error_manager.log_warning("Error‑rate limiter TRIGGERED – running cooldown cycle")
            try:
                hm.set_paused(True)
                wifi.disconnect()
                led.set_color("red", blink=False)
            except Exception as e:  # noqa: BLE001
                error_manager.log_error(f"Limiter prep: {e}")

            error_manager.reset_error_rate_limiter()

            try:
                hm.set_paused(False)
                wifi.update()
            except Exception as e:  # noqa: BLE001
                error_manager.log_error(f"Limiter resume: {e}")
        await asyncio.sleep(1)


async def main_status_task(hm, ot_ctl, wifi, led):
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

def build_menu(cfg_mgr, cfg, wifi, hm, gui_mgr, ot_ctl):
    def save(sec, key, val):
        cfg_mgr.set_value(sec, key, val)
        cfg_mgr.save_config()
        cfg.update(load_config(cfg_mgr.filename)[1])
        
        # Update controller state when OT settings change
        if sec == "OT":
            if key == "ENABLE_CONTROLLER":
                ot_ctl.controller_enabled = val
            elif key == "ENABLE_HEATING":
                ot_ctl.heating_enabled = val
            elif key == "ENABLE_DHW":
                ot_ctl.dhw_enabled = val
            elif key == "MANUAL_HEATING":
                ot_ctl.manual_heating = val
            elif key == "MANUAL_HEATING_SETPOINT":
                ot_ctl.manual_heating_setpoint = val
            elif key == "DHW_SETPOINT":
                ot_ctl.dhw_setpoint = val
            elif key == "MAX_HEATING_SETPOINT":
                ot_ctl.ot_max_heating_setpoint = val

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
            FloatField("Max Heating SP", ot_ctl.ot_max_heating_setpoint, lambda v: save("OT", "MAX_HEATING_SETPOINT", v)),
            FloatField("Manual Heating SP", ot_ctl.manual_heating_setpoint, lambda v: save("OT", "MANUAL_HEATING_SETPOINT", v)),
            FloatField("Manual DHW SP", ot_ctl.dhw_setpoint, lambda v: save("OT", "DHW_SETPOINT", v)),
            BoolField("Manual Heating", ot_ctl.manual_heating, lambda v: save("OT", "MANUAL_HEATING", v)),
            BoolField("Takeover Control", ot_ctl.controller_enabled, lambda v: save("OT", "ENABLE_CONTROLLER", v)),
            BoolField("Enable Heating", ot_ctl.heating_enabled, lambda v: save("OT", "ENABLE_HEATING", v)),
            BoolField("Enable DHW", ot_ctl.dhw_enabled, lambda v: save("OT", "ENABLE_DHW", v)),
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
            Action("Fake Error", lambda: error_manager.log_error("Fake Error")),
        ]))

    return Menu("Main Menu", items)


# --------------------------------------------------------------------------- #
#  Background task registration
# --------------------------------------------------------------------------- #

def schedule_tasks(loop, *, wifi, hm, led, ot_ctl, hid):
    for coro in (
        wifi_task(wifi), led_task(led), homematic_task(hm), opentherm_task(ot_ctl),
        poll_buttons_task(hid), main_status_task(hm, ot_ctl, wifi, led),
        error_rate_limiter_task(hm, wifi, led),
    ):
        loop.create_task(coro)


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #

def main():  # noqa: C901
    # -------------------------------- Hardware & services ------------------- #
    try:
        display, led, buttons, ot_driver = init_hardware()
    except Exception as e:  # noqa: BLE001
        handle_fatal_error("Hardware", None, None, str(e))
        return

    try:
        cfg_mgr, cfg = load_config()
        print(f"DEBUG: {DEBUG}")
        wifi = WiFiManager(cfg["ssid"], cfg["wifi_pass"], unique_hardware_name()[:15])
        hm = HomematicDataService(
            f"http://{cfg['ccu_ip']}/api/homematic.cgi",
            cfg["ccu_user"], cfg["ccu_pass"], cfg["valve_type"],
        )
        ot_ctl = OpenthermController(ot_driver, cfg["ot_max_heating_setpoint"])
        
        # Set initial controller state from config
        ot_ctl.controller_enabled = cfg["ot_enable_controller"]
        ot_ctl.manual_heating = cfg["ot_manual_heating"]
        ot_ctl.manual_heating_setpoint = cfg["ot_manual_heating_setpoint"]
        ot_ctl.heating_enabled = cfg["ot_enable_heating"]
        ot_ctl.dhw_enabled = cfg["ot_enable_dhw"]
        ot_ctl.dhw_setpoint = cfg["ot_dhw_setpoint"]

        
        base = cfg["mqtt_base_topic"]

    except Exception as e:  # noqa: BLE001
        handle_fatal_error("ServiceInit", display, led, str(e))
        return

    # -------------------------------- GUI ----------------------------------- #
    try:
        gui = GUIManager(display, buttons)
        # Build menu with a reference to the OpenTherm controller
        root_menu = build_menu(cfg_mgr, cfg, wifi, hm, gui, ot_ctl)
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
        # Page 4: Manual settings
        mon.add_page(Page(lambda: f"DHW SP: {ot_ctl.dhw_setpoint:.1f}",
                           lambda: f"Manual Heat: {ot_ctl.manual_heating}"))
        # Page 5: Current OT set‑points
        mon.add_page(Page(lambda: f"Heating SP: {ot_ctl.get_current_heating_setpoint():.1f}",
                           lambda: f"DHW SP: {ot_ctl.get_current_dhw_setpoint():.1f}"))
        # Page 6: OT controller status
        mon.add_page(Page(lambda: f"OT State: {'On' if ot_ctl.controller_enabled else 'Off'}",
                           lambda: f"Heat: {'On' if ot_ctl.heating_enabled else 'Off'} DHW: {'On' if ot_ctl.dhw_enabled else 'Off'}"))
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
    schedule_tasks(loop, wifi=wifi, hm=hm, led=led, ot_ctl=ot_ctl, hid=buttons)

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        print("KeyboardInterrupt  shutdown")
    finally:
        display.clear()
        ot_driver.close()
        led.direct_send_color("red")
        asyncio.new_event_loop()


if __name__ == "__main__":
    main()
