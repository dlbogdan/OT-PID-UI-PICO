# test_otgw_controller.py
import uasyncio
import time
import sys
import select
from altcontroller_otgw import OpenThermController, OTGW_RESPONSE_OK
from lib.manager_error import ErrorManager # Assuming ErrorManager is in lib

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
    print("\n--- Menu ---")
    print("1. Take Control (CS=40)")
    print("2. Relinquish Control (CS=0)")
    print("3. Set Control Setpoint (CS)")
    print("4. Set DHW Setpoint (SW)")
    print("5. Set Max Modulation (MM)")
    print("6. Toggle Central Heating (CH)")
    print("7. Toggle Hot Water Mode (HW=1/0)")
    print("8. Set Max CH Setpoint (SH)")
    print("9. Set Ventilation (VS %)")
    print("10. Set Control Setpoint 2 (C2)")
    print("11. Toggle CH2 Enable (H2)")
    print("R. Reset Boiler Counter (RS)")
    print("M. Show Menu")
    print("Enter choice:")

async def process_command(cmd, controller):
    """Process the user's menu command."""
    cmd = cmd.strip().lower()
    print(f"\nProcessing command: '{cmd}'")

    if cmd == '1':
        print("Attempting to take control...")
        # Run in background so main loop isn't blocked by command wait
        uasyncio.create_task(controller.take_control(initial_setpoint=40.0))
    elif cmd == '2':
        print("Attempting to relinquish control...")
        uasyncio.create_task(controller.relinquish_control())
    elif cmd == '3':
        # This part IS blocking, but only briefly to get user input
        try:
            value = float(input("  Enter Control Setpoint (e.g., 55.0): "))
            print(f"Setting CS to {value}...")
            uasyncio.create_task(controller.set_control_setpoint(value))
        except ValueError:
            print("  Invalid temperature.")
    elif cmd == '4':
        try:
            value = float(input("  Enter DHW Setpoint (e.g., 48.0): "))
            print(f"Setting SW to {value}...")
            uasyncio.create_task(controller.set_dhw_setpoint(value))
        except ValueError:
            print("  Invalid temperature.")
    elif cmd == '5':
        try:
            value = int(input("  Enter Max Modulation (0-100): "))
            if 0 <= value <= 100:
                print(f"Setting MM to {value}...")
                uasyncio.create_task(controller.set_max_modulation(value))
            else:
                print("  Value must be between 0 and 100.")
        except ValueError:
            print("  Invalid percentage.")
    elif cmd == '6': # Toggle CH - Use getter
        if controller.is_active():
            current_state = controller.is_ch_enabled()
            new_state = not current_state
            print(f"Toggling CH from {format_value(current_state)} to {format_value(new_state)}...")
            uasyncio.create_task(controller.set_central_heating(new_state))
        else:
            print("  Cannot toggle CH, controller not active.")
    elif cmd == '7': # Toggle HW - Use getter
         # HW command uses 0/1 for enable/disable
         current_state = controller.is_dhw_enabled()
         new_state_bool = not current_state
         new_state_cmd = 1 if new_state_bool else 0 # Convert bool to 0/1 for command
         print(f"Toggling HW Enable from {format_value(current_state)} to {format_value(new_state_bool)} (Using HW={new_state_cmd})...")
         uasyncio.create_task(controller.set_hot_water_mode(new_state_cmd))
         # Note: HW command might override thermostat even if controller isn't active.
    elif cmd == '8': # Set Max CH Setpoint (SH)
        try:
            value = float(input("  Enter Max CH Setpoint (e.g., 75.0, 0=auto): "))
            print(f"Setting SH to {value}...")
            uasyncio.create_task(controller.set_max_ch_setpoint(value))
        except ValueError:
            print("  Invalid temperature.")
    elif cmd == '9': # Set Ventilation (VS)
        try:
            value = int(input("  Enter Ventilation Setpoint (0-100%): "))
            if 0 <= value <= 100:
                print(f"Setting VS to {value}%...")
                uasyncio.create_task(controller.set_ventilation_setpoint(value))
            else:
                print("  Value must be between 0 and 100.")
        except ValueError:
            print("  Invalid percentage.")
    elif cmd == '10': # Set Control Setpoint 2 (C2)
        try:
            value = float(input("  Enter Control Setpoint 2 (e.g., 40.0): "))
            print(f"Setting C2 to {value}...")
            uasyncio.create_task(controller.set_control_setpoint_2(value))
        except ValueError:
            print("  Invalid temperature.")
    elif cmd == '11': # Toggle CH2 Enable (H2)
        if controller.is_active(): # Assumes H2 only works when C2 is active (and C2 requires controller active)
            # Need getter for H2 status (from ID 0, master bit 4)
            # Placeholder: Assume toggling to OFF (0)
            print("Toggling CH2 (requires getter - placeholder: setting H2=0)...")
            uasyncio.create_task(controller.set_central_heating_2(False))
            # TODO: Add getter is_ch2_enabled() to controller and use it here
        else:
            print("  Cannot toggle CH2, controller not active.")
    elif cmd == 'r': # Reset Counter (RS)
        try:
            # List valid counters from OTGW docs
            print("  Valid counters: HBS, HBH, HPS, HPH, WBS, WBH, WPS, WPH")
            counter_name = input("  Enter counter name to reset: ").strip().upper()
            print(f"Attempting to reset counter {counter_name}...")
            uasyncio.create_task(controller.reset_boiler_counter(counter_name))
        except Exception as e:
            print(f"  Error getting input: {e}")
    elif cmd == 'm':
        pass # Menu will be printed by the main loop after command processing
    else:
        print("  Unknown command.")

    # Give command task time to start/send
    await uasyncio.sleep_ms(100)
    print_menu() # Show menu again after processing

async def main():
    print("Starting OTGW Controller Monitor Script...")
    error_mgr = ErrorManager(debug_level=DEBUG_LEVEL)
    controller = OpenThermController(error_mgr)

    print("Starting controller tasks...")
    await controller.start()

    # Allow some time for UART connection
    await uasyncio.sleep(2)

    last_print_time = time.time()
    current_input = ""
    spoll = select.poll()
    spoll.register(sys.stdin, select.POLLIN)

    print_menu() # Initial menu display

    try:
        while True:
            # --- Status Printing --- (Runs periodically)
            current_time = time.time()
            if current_time - last_print_time >= PRINT_INTERVAL_S:
                print(f"\n--- Status @ {current_time:.0f} ---")
                print(f"  Controller Active: {format_value(controller.is_active())}")
                print(f"  Fault Present:     {format_value(controller.is_fault_present())}")
                print(f"  CH Enabled:        {format_value(controller.is_ch_enabled())}")
                print(f"  DHW Enabled:       {format_value(controller.is_dhw_enabled())}")
                print(f"  Flame On:          {format_value(controller.is_flame_on())}")
                print(f"  Cooling Enabled:   {format_value(controller.is_cooling_enabled())}")
                print(f"  Fault Flags:       {format_value(controller.get_fault_flags())}") # Shows active flags
                print(f"  OEM Fault Code:    0x{controller.get_oem_fault_code() or 0:02X}")
                print("  ---------------- Temperatures ----------------")
                print(f"  Room Temp:         {format_value(controller.get_room_temperature())} C")
                print(f"  Boiler Water Temp: {format_value(controller.get_boiler_water_temp())} C")
                print(f"  DHW Temp:          {format_value(controller.get_dhw_temperature())} C")
                print(f"  Outside Temp:      {format_value(controller.get_outside_temperature())} C")
                print(f"  Return Water Temp: {format_value(controller.get_return_water_temp())} C")
                print("  ---------------- Setpoints -------------------")
                print(f"  Control Setpoint:  {format_value(controller.get_control_setpoint())} C")
                print(f"  Control Setpoint2: {format_value(controller.get_control_setpoint_2())} C")
                print(f"  Room Setpoint:     {format_value(controller.get_room_setpoint())} C")
                print(f"  DHW Setpoint:      {format_value(controller.get_dhw_setpoint())} C")
                print(f"  Max CH Setpoint:   {format_value(controller.get_max_ch_water_setpoint())} C")
                print("  ---------------- Modulation & Other ----------")
                print(f"  Modulation Level:  {format_value(controller.get_relative_modulation())} %")
                print(f"  Max Modulation:    {format_value(controller.get_max_relative_modulation())} %")
                print(f"  Ventilation Level: {format_value(controller.get_ventilation_setpoint())} %")
                print(f"  CH Water Pressure: {format_value(controller.get_ch_water_pressure())} bar")

                last_print_time = current_time

            # --- Input Handling --- (Runs every loop iteration)
            # Check if input is available without blocking
            if spoll.poll(0):
                char = sys.stdin.read(1)
                if char in ('\r', '\n'): # Enter key pressed
                    await process_command(current_input, controller)
                    current_input = "" # Reset buffer
                elif char == '\x08' or char == '\x7f': # Handle backspace/delete
                     if current_input:
                         current_input = current_input[:-1]
                         sys.stdout.write('\b \b') # Erase char on screen
                # Check if character is printable ASCII (MicroPython doesn't have str.isprintable)
                elif 32 <= ord(char) <= 126:
                    current_input += char
                    sys.stdout.write(char) # Echo printable characters

            # Keep loop responsive
            await uasyncio.sleep_ms(50) # Shorter sleep for more responsive input

    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    except Exception as e:
        print(f"An error occurred in main loop: {e}")
        # import sys # Already imported
        sys.print_exception(e)
    finally:
        print("\n--- Stopping Controller ---")
        # Unregister stdin
        spoll.unregister(sys.stdin)
        await controller.stop()
        print("Controller stopped.")

if __name__ == "__main__":
    uasyncio.run(main()) 