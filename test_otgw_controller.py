# test_otgw_controller.py
import uasyncio
import time
import sys
import select
from controllers.controller_otgw import OpenThermController # Keep controller import for instantiation
from managers.manager_otgw import OpenThermManager, CMD_STATUS_PENDING, CMD_STATUS_SUCCESS # Import Manager
from managers.manager_logger import Logger
from platform_spec import HWUART
# Instantiate the Logger
error_manager = Logger()

# --- Configuration ---
# Set a debug level (0=Off, 1=Warnings/Errors, 2=Info, 3=Verbose)
DEBUG_LEVEL = 2
PRINT_INTERVAL_S = 5 # How often to print status

# --- Helper to format values --- (Simplified)
def format_value(value):
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, bool):
        return "ON" if value else "OFF"
    if isinstance(value, dict):
        # Basic dict formatting, could be expanded
        active_flags = [name for name, val in value.items() if val == 1]
        return f"[{', '.join(active_flags) or 'None'}]"
    return str(value)

def print_menu():
    error_manager.info("\n--- Menu ---")
    error_manager.info("1. Take Control (CS=40) - Note: Currently Blocks")
    error_manager.info("2. Relinquish Control (CS=0)")
    error_manager.info("3. Set Control Setpoint (CS)")
    error_manager.info("4. Set DHW Setpoint (SW)")
    error_manager.info("5. Set Max Modulation (MM)")
    error_manager.info("6. Toggle Central Heating (CH)")
    error_manager.info("7. Toggle Hot Water Mode (HW=1/0)")
    error_manager.info("8. Set Max CH Setpoint (SH)")
    error_manager.info("9. Set Ventilation (VS %)")
    error_manager.info("10. Set Control Setpoint 2 (C2)")
    error_manager.info("11. Toggle CH2 Enable (H2)")
    error_manager.info("R. Reset Boiler Counter (RS)")
    error_manager.info("P. Request Priority Message (PM)")
    error_manager.info("--- Thermostat Overrides ---")
    error_manager.info("T. Set Temporary Room Setpoint (TT)")
    error_manager.info("C. Set Constant Room Setpoint (TC)")
    error_manager.info("S. Set Thermostat Clock (SC)")
    error_manager.info("L. Show Last Command Statuses") # New option
    error_manager.info("M. Show Menu")
    error_manager.info("Enter choice:")


# Changed function signature to accept manager
# Reverted: No longer async, as manager methods are likely synchronous wrappers
def process_command(cmd, manager: OpenThermManager):
    """Process the user's menu command using the OpenThermManager."""
    cmd = cmd.strip().lower()
    error_manager.info(f"\nProcessing command: '{cmd}'")
    launched = False # Flag to indicate if a command task was launched
    # command_successful = None # Reverted

    if cmd == '1':
        error_manager.info("Attempting to take control (non-blocking)...")
        # Call the non-blocking manager method
        launched = manager.take_control()
        # The command now runs in the background. Check status with 'L' later.
        # manager.take_control(initial_setpoint=40.0)
        # TODO: Manager should ideally return True/False if task was launched - DONE
    elif cmd == '2':
        error_manager.info("Attempting to relinquish control...")
        # Call the manager method directly
        launched = manager.relinquish_control()
        # command_successful = (status_code == 0) # Reverted
        # print(f"  Relinquish Control Result: Status={status_code}, Response='{response_data}'") # Reverted
    elif cmd == '3':
        try:
            value = float(input("  Enter Control Setpoint (e.g., 55.0): "))
            error_manager.info(f"Requesting set CS to {value}...")
            launched = manager.set_control_setpoint(value)
        except ValueError:
            error_manager.error("  Invalid temperature.")
    elif cmd == '4':
        try:
            value = float(input("  Enter DHW Setpoint (e.g., 48.0): "))
            error_manager.info(f"Requesting set SW to {value}...")
            launched = manager.set_dhw_setpoint(value)
        except ValueError:
            error_manager.error("  Invalid temperature.")
    elif cmd == '5':
        try:
            value = int(input("  Enter Max Modulation (0-100): "))
            if 0 <= value <= 100:
                error_manager.info(f"Requesting set MM to {value}...")
                launched = manager.set_max_modulation(value)
            else:
                error_manager.error("  Value must be between 0 and 100.")
        except ValueError:
            error_manager.error("  Invalid percentage.")
    elif cmd == '6': # Toggle CH - Use manager's proxied getter
        if manager.is_active():
            current_state = manager.is_ch_enabled()
            new_state = not current_state
            error_manager.info(f"Requesting toggle CH from {format_value(current_state)} to {format_value(new_state)}...")
            launched = manager.set_central_heating(new_state)
        else:
            error_manager.error("  Cannot toggle CH, controller not active.")
    elif cmd == '7': # Toggle HW - Use manager's proxied getter
         current_state = manager.is_dhw_enabled()
         new_state_bool = not current_state
         new_state_cmd = 1 if new_state_bool else 0
         error_manager.info(f"Requesting toggle HW Enable from {format_value(current_state)} to {format_value(new_state_bool)} (Using HW={new_state_cmd})...")
         launched = manager.set_hot_water_mode(new_state_cmd)
    elif cmd == '8':
        try:
            value = float(input("  Enter Max CH Setpoint (e.g., 75.0, 0=auto): "))
            error_manager.info(f"Requesting set SH to {value}...")
            launched = manager.set_max_ch_setpoint(value)
        except ValueError:
            error_manager.error("  Invalid temperature.")
    elif cmd == '9':
        try:
            value = int(input("  Enter Ventilation Setpoint (0-100%): "))
            if 0 <= value <= 100:
                error_manager.info(f"Requesting set VS to {value}%...")
                launched = manager.set_ventilation_setpoint(value)
            else:
                error_manager.error("  Value must be between 0 and 100.")
        except ValueError:
            error_manager.error("  Invalid percentage.")
    elif cmd == '10':
        try:
            value = float(input("  Enter Control Setpoint 2 (e.g., 40.0): "))
            error_manager.info(f"Requesting set C2 to {value}...")
            launched = manager.set_control_setpoint_2(value)
        except ValueError:
            error_manager.error("  Invalid temperature.")
    elif cmd == '11': # Toggle CH2 Enable (H2)
        if manager.is_active():
            # TODO: Add manager.is_ch2_enabled() proxy
            error_manager.info("Toggling CH2 (requires getter - placeholder: setting H2=0)...")
            launched = manager.set_central_heating_2(False)
        else:
            error_manager.error("  Cannot toggle CH2, controller not active.")
    elif cmd == 'r':
        try:
            error_manager.info("  Valid counters: HBS, HBH, HPS, HPH, WBS, WBH, WPS, WPH")
            counter_name = input("  Enter counter name to reset: ").strip().upper()
            error_manager.info(f"Requesting reset counter {counter_name}...")
            launched = manager.reset_boiler_counter(counter_name)
        except Exception as e:
            error_manager.error(f"  Error getting input: {e}")
    elif cmd == 'p':
        try:
            value = int(input("  Enter Data ID to request (0-255): "))
            error_manager.info(f"Requesting priority message for ID {value}...")
            launched = manager.request_priority_message(value)
        except ValueError:
            error_manager.error("  Invalid Data ID.")
    elif cmd == 't':
        try:
            value = float(input("  Enter Temporary Setpoint (0.0-30.0, 0=cancel): "))
            error_manager.info(f"Requesting set TT to {value:.2f}...")
            launched = manager.set_temporary_room_setpoint_override(value)
        except ValueError:
            error_manager.error("  Invalid temperature.")
    elif cmd == 'c':
        try:
            value = float(input("  Enter Constant Setpoint (0.0-30.0, 0=cancel): "))
            error_manager.info(f"Requesting set TC to {value:.2f}...")
            launched = manager.set_constant_room_setpoint_override(value)
        except ValueError:
            error_manager.error("  Invalid temperature.")
    elif cmd == 's':
        try:
            time_str = input("  Enter Time (HH:MM): ").strip()
            day_int = int(input("  Enter Day of Week (1=Mon, 7=Sun): "))
            error_manager.info(f"Requesting set SC to {time_str} / {day_int}...")
            launched = manager.set_thermostat_clock(time_str, day_int)
        except ValueError:
            error_manager.error("  Invalid day or time format.")
        except Exception as e:
             error_manager.error(f"  Error setting clock: {e}")
    elif cmd == 'l': # Show Last Command Statuses
         error_manager.info("\n--- Last Command Statuses ---")
         states = manager._command_states # Access internal state for display
         if not states:
             error_manager.info("  No commands issued yet.")
         else:
             for code, state_data in sorted(states.items()):
                 status = state_data.get("status", "unknown")
                 result = state_data.get("result", "")
                 err_code = state_data.get("error_code")
                 ts = state_data.get("last_update", 0)
                 error_manager.info(f"  {code:<5}: {status:<10} Err:{err_code!s:<5} Res:{result!s:<20} @ {ts:.0f}")
         # No task launched for this command
    elif cmd == 'm':
        pass
    else:
        error_manager.error("  Unknown command.")

    if launched:
        error_manager.info("  Command task launched successfully.")
    elif cmd not in ('m', 'l', '1'): # Don't print for menu, status list, or blocking take_control
        error_manager.error("  Command task NOT launched (maybe pending or invalid?).")

    # No longer need sleep here, menu is printed after processing input
    # await uasyncio.sleep_ms(100)
    print_menu() # Show menu again after processing

async def main():
    error_manager.info("Starting OTGW Controller Monitor Script...")
    error_mgr = Logger(debug_level=DEBUG_LEVEL)
    # Instantiate Controller first
    controller = OpenThermController(HWUART())
    # Instantiate Manager, passing the controller
    manager = OpenThermManager(controller)

    error_manager.info("Starting manager tasks...")
    # Start the manager, which starts the controller and handles delays
    await manager.start()

    # Allow some time for UART connection - REMOVED, handled by manager.start()
    # await uasyncio.sleep(2)

    last_print_time = time.time()
    current_input = ""
    spoll = select.poll()
    spoll.register(sys.stdin, select.POLLIN)

    print_menu() # Initial menu display

    try:
        while True:
            # --- Status Printing --- (Runs periodically using Manager's proxy getters)
            current_time = time.time()
            if current_time - last_print_time >= PRINT_INTERVAL_S:
                error_manager.info(f"\n--- Status @ {current_time:.0f} ---")
                # --- Basic Status & Flags ---
                error_manager.info(f"  Boiler Connected:  {format_value(manager.is_boiler_connected())}")
                error_manager.info(f"  Controller Active: {format_value(manager.is_active())}")
                error_manager.info(f"  Fault Present:     {format_value(manager.is_fault_present())}")
                error_manager.info(f"  CH Enabled:        {format_value(manager.is_ch_enabled())}")
                error_manager.info(f"  DHW Enabled:       {format_value(manager.is_dhw_enabled())}")
                error_manager.info(f"  Flame On:          {format_value(manager.is_flame_on())}")
                error_manager.info(f"  Cooling Enabled:   {format_value(manager.is_cooling_enabled())}")
                # print(f"  CH2 Enabled:       {format_value(manager.is_ch2_enabled())}") # TODO: Add getter proxy
                error_manager.info(f"  Fault Flags:       {format_value(manager.get_fault_flags())}")
                error_manager.info(f"  OEM Fault Code:    0x{manager.get_oem_fault_code() or 0:02X}")

                # --- Temperatures ---
                error_manager.info("  ---------------- Temperatures ----------------")
                error_manager.info(f"  Room Temp:         {format_value(manager.get_room_temperature())} C")
                error_manager.info(f"  Boiler Water Temp: {format_value(manager.get_boiler_water_temp())} C")
                error_manager.info(f"  DHW Temp:          {format_value(manager.get_dhw_temperature())} C")
                error_manager.info(f"  Outside Temp:      {format_value(manager.get_outside_temperature())} C")
                error_manager.info(f"  Return Water Temp: {format_value(manager.get_return_water_temp())} C")

                # --- Setpoints ---
                error_manager.info("  ---------------- Setpoints -------------------")
                error_manager.info(f"  Control Setpoint:  {format_value(manager.get_control_setpoint())} C")
                error_manager.info(f"  Control Setpoint2: {format_value(manager.get_control_setpoint_2())} C")
                error_manager.info(f"  Room Setpoint:     {format_value(manager.get_room_setpoint())} C")
                error_manager.info(f"  DHW Setpoint:      {format_value(manager.get_dhw_setpoint())} C")
                error_manager.info(f"  Max CH Setpoint:   {format_value(manager.get_max_ch_water_setpoint())} C")

                # --- Modulation & Other ---
                error_manager.info("  ---------------- Modulation & Other ----------")
                error_manager.info(f"  Modulation Level:  {format_value(manager.get_relative_modulation())} %")
                error_manager.info(f"  Max Modulation:    {format_value(manager.get_max_relative_modulation())} %")
                error_manager.info(f"  Ventilation Level: {format_value(manager.get_ventilation_setpoint())} %")
                error_manager.info(f"  CH Water Pressure: {format_value(manager.get_ch_water_pressure())} bar")

                last_print_time = current_time

            # --- Input Handling --- (existing)
            # Check if input is available without blocking
            if spoll.poll(0):
                char = sys.stdin.read(1)
                if char in ('\r', '\n'): # Enter key pressed
                    # Pass manager to process_command now
                    # Call synchronously
                    process_command(current_input, manager)
                    current_input = "" # Reset buffer
                elif char == '\x08' or char == '\x7f': # Handle backspace/delete
                     if current_input:
                         current_input = current_input[:-1]
                         sys.stdout.write('\b \b') # Erase char on screen
                elif 32 <= ord(char) <= 126:
                    current_input += char
                    sys.stdout.write(char) # Echo printable characters

            # Keep loop responsive
            await uasyncio.sleep_ms(50)

    except KeyboardInterrupt:
        error_manager.error("\nInterrupted by user.")
    except Exception as e:
        error_manager.error(f"An error occurred in main loop: {e}")
        sys.print_exception(e)
    finally:
        error_manager.info("\n--- Stopping Manager ---")
        spoll.unregister(sys.stdin)
        # Stop the manager, which stops the controller
        await manager.stop()
        error_manager.info("Manager stopped.")

if __name__ == "__main__":
    uasyncio.run(main()) 