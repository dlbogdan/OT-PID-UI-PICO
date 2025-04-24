import uasyncio
import time
from controllers.controller_otgw import OpenThermController, OTGW_RESPONSE_OK, OTGW_RESPONSE_TIMEOUT, OTGW_RESPONSE_UNKNOWN
from managers.manager_logger import Logger

# Status constants for command tracking
CMD_STATUS_IDLE = "idle"
CMD_STATUS_PENDING = "pending"
CMD_STATUS_SUCCESS = "success"
CMD_STATUS_TIMEOUT = "timeout"
CMD_STATUS_ERROR = "error"
CMD_STATUS_VALIDATION_ERROR = "validation_error"

class OpenThermManager:
    """
    Manages interaction with OpenThermController, providing a non-blocking
    interface for commands and tracking their execution status.
    """
    def __init__(self, controller: OpenThermController, error_manager: Logger):
        self.controller = controller
        self.error_manager = error_manager
        # Stores the state of the last issued command for each type
        # Key: command code (e.g., "CS", "SW"), Value: dict
        self._command_states = {}

    async def start(self):
        """Starts the underlying controller and waits briefly for UART setup."""
        self.error_manager.info("Manager starting controller...")
        await self.controller.start()
        # Allow some time for UART connection after controller tasks start
        await uasyncio.sleep(2)
        self.error_manager.info("Manager finished starting controller.")

    async def stop(self):
        """Stops the underlying controller."""
        self.error_manager.info("Manager stopping controller...")
        await self.controller.stop()
        self.error_manager.info("Manager finished stopping controller.")

    # --- Internal Task Execution ---
    async def _execute_command_task(self, cmd_code: str, controller_method, *args):
        """Internal helper to run controller methods as tasks and track status."""
        try:
            # Await the actual controller method
            result = await controller_method(*args)

            # Handle different return types from controller methods
            if isinstance(result, tuple) and len(result) == 2:
                # Check the type of the first element to differentiate tuple types
                if isinstance(result[0], bool):
                    # Case 1: Method returns (success: bool, message: str) - e.g., take_control
                    success, response_data = result
                    if success:
                        self._update_command_state(cmd_code, CMD_STATUS_SUCCESS, result=response_data, error_code=OTGW_RESPONSE_OK)
                    else:
                        self._update_command_state(cmd_code, CMD_STATUS_ERROR, result=response_data, error_code=1) # Use generic error 1
                elif isinstance(result[0], int):
                    # Case 2: Method returns (status_code: int, response_data: any)
                    status_code, response_data = result
                    if status_code == OTGW_RESPONSE_OK:
                        self._update_command_state(cmd_code, CMD_STATUS_SUCCESS, result=response_data, error_code=status_code)
                    elif status_code == OTGW_RESPONSE_TIMEOUT:
                         self._update_command_state(cmd_code, CMD_STATUS_TIMEOUT, result=response_data, error_code=status_code)
                    else: # Other specific errors from OTGW or validation errors
                         self._update_command_state(cmd_code, CMD_STATUS_ERROR, result=response_data, error_code=status_code)
                else:
                    # Unknown 2-element tuple format
                    self.error_manager.warning(f"Command {cmd_code} controller method returned unexpected 2-tuple format: {result}. Assuming error.")
                    self._update_command_state(cmd_code, CMD_STATUS_ERROR, result=repr(result), error_code=OTGW_RESPONSE_UNKNOWN)
            else:
                 # Assume other return types indicate an unexpected issue or simple success
                 self.error_manager.warning(f"Command {cmd_code} controller method returned unexpected type: {type(result)}. Assuming success.")
                 self._update_command_state(cmd_code, CMD_STATUS_SUCCESS, result=repr(result), error_code=OTGW_RESPONSE_OK)

        except Exception as e:
            self.error_manager.error(f"Exception during command task {cmd_code}: {e}")
            self._update_command_state(cmd_code, CMD_STATUS_ERROR, result=str(e), error_code=OTGW_RESPONSE_UNKNOWN)

    def _update_command_state(self, cmd_code: str, status, result=None, error_code=None):
        """Updates the internal state dictionary for a given command."""
        self._command_states[cmd_code] = {
            "status": status,
            "result": result,         # Response data from OTGW or error message
            "error_code": error_code, # OTGW_RESPONSE_... code
            "last_update": time.time()
        }
        self.error_manager.info(f"Command {cmd_code} state updated: {status}") # Optional logging

    def _launch_command(self, cmd_code: str, controller_method, *args) -> bool:
        """Checks if command is pending, updates state, and launches task."""
        # Basic check: Don't launch if already pending (could be made more robust)
        if self._command_states.get(cmd_code, {}).get("status") == CMD_STATUS_PENDING:
            self.error_manager.warning(f"Command {cmd_code} is already pending. Ignoring new request.")
            return False

        self._update_command_state(cmd_code, CMD_STATUS_PENDING)
        uasyncio.create_task(self._execute_command_task(
            cmd_code,
            controller_method,
            *args
        ))
        return True # Task launched

    # --- Public Command Methods (Non-blocking) ---

    # - Boiler Control -
    def take_control(self, initial_setpoint=10.0):
        # Refactored to use _launch_command for non-blocking execution
        # Uses "TCtrl" as the command code for tracking.
        self.error_manager.info(f"Launching take_control task (CS={initial_setpoint})...")
        return self._launch_command("TCtrl", self.controller.take_control, initial_setpoint)

    def relinquish_control(self):
        # Uses "CS0" as the command code for tracking relinquish (CS=0).
        return self._launch_command("CS0", self.controller.relinquish_control)

    def set_control_setpoint(self, temp):
        return self._launch_command("CS", self.controller.set_control_setpoint, temp)

    def set_dhw_setpoint(self, temp):
        return self._launch_command("SW", self.controller.set_dhw_setpoint, temp)

    def set_max_modulation(self, percentage):
        return self._launch_command("MM", self.controller.set_max_modulation, percentage)

    def set_central_heating(self, enabled: bool):
        return self._launch_command("CH", self.controller.set_central_heating, enabled)

    def set_max_ch_setpoint(self, temp):
        return self._launch_command("SH", self.controller.set_max_ch_setpoint, temp)

    def set_control_setpoint_2(self, temp):
        return self._launch_command("C2", self.controller.set_control_setpoint_2, temp)

    def set_central_heating_2(self, enabled: bool):
        return self._launch_command("H2", self.controller.set_central_heating_2, enabled)

    def set_ventilation_setpoint(self, percentage):
        return self._launch_command("VS", self.controller.set_ventilation_setpoint, percentage)

    def reset_boiler_counter(self, counter_name):
        return self._launch_command("RS", self.controller.reset_boiler_counter, counter_name)

    def set_hot_water_mode(self, state):
        return self._launch_command("HW", self.controller.set_hot_water_mode, state)

    # - Thermostat Overrides -
    def set_temporary_room_setpoint_override(self, temp):
        return self._launch_command("TT", self.controller.set_temporary_room_setpoint_override, temp)

    def set_constant_room_setpoint_override(self, temp):
        return self._launch_command("TC", self.controller.set_constant_room_setpoint_override, temp)

    def set_thermostat_clock(self, time_str, day_int):
        return self._launch_command("SC", self.controller.set_thermostat_clock, time_str, day_int)

    # - Gateway Interaction -
    def request_priority_message(self, data_id):
        return self._launch_command("PM", self.controller.request_priority_message, data_id)

    # --- Public Status Getters ---
    def get_command_status(self, cmd_code: str) -> dict | None:
        """Gets the last known status of a launched command."""
        return self._command_states.get(cmd_code)

    # Proxy getters from controller
    def get_status(self):
        return self.controller.get_status()

    def get_last_response(self, cmd_code):
        return self.controller.get_last_response(cmd_code)

    def is_active(self):
        return self.controller.is_active()

    def get_control_setpoint(self):
        return self.controller.get_control_setpoint()

    def get_master_status_flags(self):
        return self.controller.get_master_status_flags()

    def get_slave_status_flags(self):
        return self.controller.get_slave_status_flags()

    def is_ch_enabled(self):
        return self.controller.is_ch_enabled()

    def is_dhw_enabled(self):
        return self.controller.is_dhw_enabled()

    def is_cooling_enabled(self):
        return self.controller.is_cooling_enabled()

    def is_fault_present(self):
        return self.controller.is_fault_present()

    def is_flame_on(self):
        return self.controller.is_flame_on()

    def get_fault_flags(self):
        return self.controller.get_fault_flags()

    def get_oem_fault_code(self):
        return self.controller.get_oem_fault_code()

    def get_max_relative_modulation(self):
        return self.controller.get_max_relative_modulation()

    def get_room_setpoint(self):
        return self.controller.get_room_setpoint()

    def get_relative_modulation(self):
        return self.controller.get_relative_modulation()

    def get_ch_water_pressure(self):
        return self.controller.get_ch_water_pressure()

    def get_room_temperature(self):
        return self.controller.get_room_temperature()

    def get_boiler_water_temp(self):
        return self.controller.get_boiler_water_temp()

    def get_dhw_temperature(self):
        return self.controller.get_dhw_temperature()

    def get_outside_temperature(self):
        return self.controller.get_outside_temperature()

    def get_return_water_temp(self):
        return self.controller.get_return_water_temp()

    def get_dhw_setpoint(self):
        return self.controller.get_dhw_setpoint()

    def get_max_ch_water_setpoint(self):
        return self.controller.get_max_ch_water_setpoint()

    def get_control_setpoint_2(self):
        return self.controller.get_control_setpoint_2()

    def get_ventilation_setpoint(self):
        return self.controller.get_ventilation_setpoint()

    def is_boiler_connected(self):
        """Checks if the boiler appears connected based on recent messages."""
        return self.controller.is_boiler_connected() 