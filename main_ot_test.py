import uasyncio as asyncio
from hardware_config import OT_UART_ID, OT_UART_TX_PIN, OT_UART_RX_PIN, OT_UART_BAUDRATE
from lib.drivers.altdriver_opentherm import OTGWController
from manager_error import ErrorManager

# Initialize error manager
error_manager = ErrorManager()
DEBUG = error_manager.get_debuglevel()


_last_status_snapshot = {}

async def interactive_menu(controller):
    menu = """
Commands:
  1 - Set CH Setpoint
  2 - Set DHW Setpoint
  3 - Set Max CH Setpoint
  4 - Set Max Modulation
  5 - Stop Heating
  6 - Show Status
  q - Quit
"""
    print(menu)
    while True:
        cmd = input("Enter command: ").strip().lower()
        try:
            if cmd == "1":
                temp = float(input("Enter CH setpoint (°C): "))
                controller.set_heating_setpoint(temp)
            elif cmd == "2":
                temp = float(input("Enter DHW setpoint (°C): "))
                controller.set_dhw_setpoint(temp)
            elif cmd == "3":
                temp = float(input("Enter Max CH setpoint (°C): "))
                controller.set_max_ch_setpoint(temp)
            elif cmd == "4":
                percent = float(input("Enter Max Modulation (%): "))
                controller.set_max_modulation(percent)
            elif cmd == "5":
                controller.stop_heating()
            elif cmd == "6":
                print_status(controller.get_status())
            elif cmd == "q":
                print("Exiting menu...")
                break
            else:
                print("Unknown command")
        except Exception as e:
            print(f"Error: {e}")

def print_status(status):
    print("\n--- Status Updated ---")
    print("Gateway:", status['gateway'])
    print("Boiler:", status['boiler'])
    print("Env:", status['environment'])

async def monitor_changes(controller):
    global _last_status_snapshot
    while True:
        await asyncio.sleep(1)
        new_status = controller.get_status()
        if new_status != _last_status_snapshot:
            _last_status_snapshot = new_status.copy()
            print_status(new_status)

async def run_monitor():
    controller = OTGWController()
    await controller.start()
    asyncio.create_task(monitor_changes(controller))
    asyncio.create_task(interactive_menu(controller))
    while True:
        await asyncio.sleep(60)

try:
    asyncio.run(run_monitor())
except KeyboardInterrupt:
    print("Interrupted")
