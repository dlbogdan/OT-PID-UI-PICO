import uasyncio
from machine import UART, Pin
import time
import hardware_config as cfg
from lib.manager_error import ErrorManager # Assuming ErrorManager is in lib

# OTGW Response Codes
OTGW_RESPONSE_OK = 0
OTGW_RESPONSE_NG = 1 # No Good (Unknown command)
OTGW_RESPONSE_SE = 2 # Syntax Error
OTGW_RESPONSE_BV = 3 # Bad Value
OTGW_RESPONSE_OR = 4 # Out of Range
OTGW_RESPONSE_NS = 5 # No Space
OTGW_RESPONSE_NF = 6 # Not Found
OTGW_RESPONSE_OE = 7 # Overrun Error
OTGW_RESPONSE_TIMEOUT = 8
OTGW_RESPONSE_UNKNOWN = 9

# --- OpenTherm Flag Definitions ---
# Based on Protocol v2.2

# Data ID 0: Status Flags (Master:HB, Slave:LB)
OT_STATUS_MASTER_HB = {
    0: "CH Enable",
    1: "DHW Enable",
    2: "Cooling Enable",
    3: "OTC Active",
    4: "CH2 Enable",
    5: "Summer/Winter Mode", # 1=Summer
    6: "DHW Blocking",       # 1=Blocking
    # Bit 7 is reserved
}

OT_STATUS_SLAVE_LB = {
    0: "Fault Indication", # 1=Fault
    1: "CH Mode",          # 1=Active
    2: "DHW Mode",         # 1=Active
    3: "Flame Status",     # 1=On
    4: "Cooling Status",   # 1=Active
    5: "CH2 Mode",         # 1=Active
    6: "Diagnostic Indication", # 1=Diagnostic event
    # Bit 7 is reserved
}

# Data ID 5: Fault Flags & OEM Code (OEM Code: HB, Fault Flags: LB)
OT_FAULT_FLAGS_LB = {
    0: "Service Request", # 1=Active
    1: "Lockout Reset",   # 1=Enabled
    2: "Low Water Press", # 1=Fault
    3: "Gas/Flame Fault", # 1=Fault
    4: "Air Press Fault", # 1=Fault
    5: "Water Over-Temp", # 1=Fault
    # Bits 6, 7 reserved
}

# Data ID 70: V/H Control Status (Master: HB, Slave: LB) - Less common
# Add mappings if needed

# Keep-alive interval (seconds)
KEEP_ALIVE_INTERVAL = 50 # As per doc, commands like CS > 8 must be resent every minute

class OpenThermController:
    """
    Asynchronous controller for an OpenTherm Gateway (OTGW) via UART.
    """
    def __init__(self, error_manager: ErrorManager):
        self.error_manager = error_manager
        self.uart = UART(
            cfg.OT_UART_ID,
            baudrate=cfg.OT_UART_BAUDRATE,
            tx=Pin(cfg.OT_UART_TX_PIN),
            rx=Pin(cfg.OT_UART_RX_PIN),
            timeout=10, # Short timeout for readline
            timeout_char=10
        )
        self.stream = uasyncio.StreamReader(self.uart)
        self.writer = uasyncio.StreamWriter(self.uart, {})

        self._status_data = {} # Parsed data from T/B messages
        self._last_responses = {} # Stores last response string for each command code
        self._response_events = {} # Events to signal command responses
        self._command_lock = uasyncio.Lock()

        self._reader_task = None
        self._keep_alive_task = None

        self._is_controller_active = False # True if we are overriding the thermostat
        self._control_setpoint_override = 0.0 # Stores the value set by CS command
        self._control_setpoint2_override = 0.0 # Stores the value set by C2 command
        self._last_keep_alive_time = 0

        self.error_manager.log_info("OpenThermController initialized.")

    async def _uart_reader(self):
        """Task to continuously read and parse lines from OTGW."""
        self.error_manager.log_info("OTGW UART reader task started.")
        while True:
            try:
                # Use readexactly for potentially faster reads if line endings are consistent
                # However, readline is safer if lines might be incomplete/malformed
                line_bytes = await self.stream.readline()
                if not line_bytes:
                    await uasyncio.sleep_ms(50) # Avoid busy-waiting if nothing received
                    continue

                line = line_bytes.decode('ascii').strip()
                if not line:
                    continue

                self.error_manager.log_info(f"OTGW RX: {line}") # DEBUG

                # --- Message Parsing ---
                # Check for command response first (XX: Data)
                parts = line.split(':', 1)
                if len(parts) == 2 and len(parts[0]) == 2 and parts[0].isupper():
                    cmd_code = parts[0]
                    response_data = parts[1].strip()
                    self.error_manager.log_info(f"Recognized command response for {cmd_code}: {response_data}")
                    self._last_responses[cmd_code] = response_data
                    if cmd_code in self._response_events:
                        self._response_events[cmd_code].set() # Signal waiting command
                        # Optional: Clean up event now? Or let _send_command handle it?
                        # del self._response_events[cmd_code]
                    else:
                        # Unsolicited response (e.g., error reported by OTGW like NG, SE)
                        # Or response to a command we didn't wait for (less likely)
                        self.error_manager.log_warning(f"Received unsolicited/unexpected response: {line}")

                # Check for standard status/error message (SXXXXXXXX or EXX)
                elif len(line) > 1 and line[0] in ('T', 'B', 'R', 'A', 'E'):
                    msg_source = line[0]
                    hex_data = line[1:]
                    # Status message (e.g., T01234567)
                    if len(hex_data) == 8:
                         try:
                             msg_type_raw = int(hex_data[0:2], 16)
                             data_id = int(hex_data[2:4], 16)
                             val_hb = int(hex_data[4:6], 16)
                             val_lb = int(hex_data[6:8], 16)
                             self._parse_and_update_status(msg_source, msg_type_raw, data_id, val_hb, val_lb)
                         except ValueError:
                             self.error_manager.log_warning(f"Could not parse OTGW status message: {line}")
                    # OTGW Internal Error (e.g., E01)
                    elif msg_source == 'E':
                         self.error_manager.log_error(f"OTGW reported error: {line}")
                    # Other malformed T/B/R/A/E message?
                    else:
                         self.error_manager.log_warning(f"Received unparseable OTGW status/error line: {line}")

                # If it's neither a command response nor a known status/error format
                else:
                    self.error_manager.log_warning(f"Received unknown format line from OTGW: {line}")

            except uasyncio.TimeoutError:
                 # This shouldn't happen with readline unless stream closes, but handle defensively
                 await uasyncio.sleep_ms(100)
            except Exception as e:
                self.error_manager.log_error(f"Error in OTGW UART reader: {e}")
                # Consider more robust error handling, maybe reset UART?
                await uasyncio.sleep(5) # Avoid tight loop on persistent error

    def _parse_and_update_status(self, source, msg_type_raw, data_id, val_hb, val_lb):
        """Parses received status message data and updates _status_data."""
        parsed_value = None
        raw_value = (val_hb << 8) | val_lb

        try:
            # --- Add parsing logic based on Data ID ---
            if data_id == 0: # Status Flags
                parsed_value = {
                    'master': self._parse_bitfield(val_hb, OT_STATUS_MASTER_HB),
                    'slave': self._parse_bitfield(val_lb, OT_STATUS_SLAVE_LB)
                }
            elif data_id == 5: # Fault Flags & OEM Code
                 parsed_value = {
                     'oem_code': val_hb, # Store OEM code as raw byte
                     'flags': self._parse_bitfield(val_lb, OT_FAULT_FLAGS_LB)
                 }
            elif data_id in [1, 7, 8, 14, 16, 17, 18, 19, 23, 24, 25, 26, 27, 28, 31, 56, 57]: # f8.8 values
                parsed_value = self._parse_f88(val_hb, val_lb)
            elif data_id == 33: # s16 (Boiler exhaust temperature)
                # Assuming s16 uses the same logic as f8.8 but without division
                value = raw_value
                if val_hb & 0x80:
                    value = -( ( (~value) + 1 ) & 0xFFFF )
                parsed_value = value
            elif data_id in [48, 49]: # HB/LB Boundaries (s8)
                parsed_value = {
                    'lower': self._parse_s8(val_lb),
                    'upper': self._parse_s8(val_hb)
                }
            elif data_id == 70: # V/H Status flags - Add mapping if needed
                 parsed_value = {
                     'master': self._parse_bitfield(val_hb, {}), # Placeholder mapping
                     'slave': self._parse_bitfield(val_lb, {})  # Placeholder mapping
                 }
            elif data_id in [71, 77]: # u8 values (use LB)
                 parsed_value = val_lb
            elif data_id in [116, 117, 118, 119, 120, 121, 122, 123]: # u16 Counters
                parsed_value = self._parse_u16(val_hb, val_lb)
            # Add more IDs as needed
            else:
                # Keep raw for unknown IDs
                pass

            self._status_data[data_id] = {
                'source': source,
                'msg_type': msg_type_raw, # Store the message type flags as well
                'raw_value': raw_value,
                'hb': val_hb,
                'lb': val_lb,
                'parsed_value': parsed_value,
                'timestamp': time.time()
            }
            # Optional: Log successful parsing
            # self.error_manager.log_info(f"Parsed ID {data_id}: {parsed_value}")

        except Exception as e:
            self.error_manager.log_error(f"Error parsing Data ID {data_id} (HB:{val_hb}, LB:{val_lb}): {e}")
            # Store raw data even if parsing fails
            self._status_data[data_id] = {
                'source': source,
                'msg_type': msg_type_raw,
                'raw_value': raw_value,
                'hb': val_hb,
                'lb': val_lb,
                'parsed_value': None, # Indicate parsing failure
                'timestamp': time.time(),
                'error': str(e)
            }

    async def _keep_alive(self):
        """Task to periodically send commands to maintain control if needed."""
        self.error_manager.log_info("OTGW keep-alive task started.")
        while True:
            await uasyncio.sleep(KEEP_ALIVE_INTERVAL)
            if self._is_controller_active:
                now = time.time()
                resend_needed = False
                # Check if CS override needs periodic refresh
                if self._control_setpoint_override >= 8.0:
                     self.error_manager.log_info("Keep-alive: Resending CS command.")
                     await self._send_command("CS", self._control_setpoint_override, timeout=5)
                     resend_needed = True

                # Check if C2 override needs periodic refresh
                if self._control_setpoint2_override >= 8.0:
                    self.error_manager.log_info("Keep-alive: Resending C2 command.")
                    await self._send_command("C2", self._control_setpoint2_override, timeout=5)
                    resend_needed = True

                if resend_needed:
                    self._last_keep_alive_time = now # Update time only if command sent

    async def _send_command(self, cmd_code, value, timeout=2):
        """Sends a command and waits for a specific response."""
        if len(cmd_code) != 2 or not cmd_code.isupper():
            self.error_manager.log_error(f"Invalid command code format: {cmd_code}")
            return OTGW_RESPONSE_SE, None

        async with self._command_lock:
            # Use only carriage return as terminator, per OTGW docs
            cmd_str = f"{cmd_code}={value}\r"
            self.error_manager.log_info(f"OTGW TX: {cmd_str.strip()}")

            # Prepare for response
            response_event = uasyncio.Event()
            self._response_events[cmd_code] = response_event
            self._last_responses.pop(cmd_code, None) # Clear previous response

            try:
                await self.writer.awrite(cmd_str.encode('ascii'))
                await self.writer.drain() # Ensure data is sent

                # Wait for the response event triggered by _uart_reader
                await uasyncio.wait_for(response_event.wait(), timeout)

                response_data = self._last_responses.get(cmd_code)
                # Basic check: if response_data exists, assume OK for now
                # More robust: Check response_data for specific success/error indicators if possible
                # Some OTGW commands just echo the value, others might have specific OK/NG responses
                # For now, presence of any response means OK, absence means timeout.
                # We can refine this by checking known error responses (NG, SE, etc.) if the gateway
                # sends them consistently in the response data itself.
                # Example: if response_data == "NG": return OTGW_RESPONSE_NG, response_data
                return OTGW_RESPONSE_OK, response_data

            except uasyncio.TimeoutError:
                self.error_manager.log_warning(f"Timeout waiting for response to command: {cmd_code}")
                return OTGW_RESPONSE_TIMEOUT, None
            except Exception as e:
                self.error_manager.log_error(f"Error sending command {cmd_code}: {e}")
                return OTGW_RESPONSE_UNKNOWN, None
            finally:
                # Clean up the event for this specific command instance
                if cmd_code in self._response_events:
                    del self._response_events[cmd_code]


    async def start(self):
        """Starts the background reader and keep-alive tasks."""
        if self._reader_task is None:
            self._reader_task = uasyncio.create_task(self._uart_reader())
            self.error_manager.log_info("Scheduled OTGW UART reader task.")
        else:
            self.error_manager.log_warning("OTGW reader task already started.")

        if self._keep_alive_task is None:
             self._keep_alive_task = uasyncio.create_task(self._keep_alive())
             self.error_manager.log_info("Scheduled OTGW keep-alive task.")
        else:
             self.error_manager.log_warning("OTGW keep-alive task already started.")


    async def stop(self):
        """Stops the background tasks."""
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except uasyncio.CancelledError:
                pass
            self._reader_task = None
            self.error_manager.log_info("OTGW UART reader task stopped.")

        if self._keep_alive_task:
             self._keep_alive_task.cancel()
             try:
                 await self._keep_alive_task
             except uasyncio.CancelledError:
                 pass
             self._keep_alive_task = None
             self.error_manager.log_info("OTGW keep-alive task stopped.")

        # Close UART? Maybe not, allow restarting
        # await self.writer.aclose()
        # self.uart.deinit()

    # --- Control Methods ---

    async def take_control(self, initial_setpoint=10.0):
        """
        Takes control from the thermostat by setting CS and CH.
        Args:
            initial_setpoint: The initial control setpoint to set (must be >= 0).
        """
        if initial_setpoint < 0:
             self.error_manager.log_warning("Initial setpoint must be >= 0. Using 10.0.")
             initial_setpoint = 10.0

        self.error_manager.log_info(f"Attempting to take control with CS={initial_setpoint}...")
        # 1. Set Control Setpoint
        status, _ = await self._send_command("CS", initial_setpoint)
        if status != OTGW_RESPONSE_OK:
            self.error_manager.log_error("Failed to set initial Control Setpoint (CS). Cannot take control.")
            return False

        # 2. Enable Central Heating via Gateway
        status, _ = await self._send_command("CH", 1)
        if status != OTGW_RESPONSE_OK:
            self.error_manager.log_error("Failed to enable Central Heating (CH=1). Control may be partial.")
            # Decide if we proceed or rollback? For now, proceed but log error.
            # To rollback: await self._send_command("CS", 0)
            # return False

        self.error_manager.log_info("Successfully took control (CS set, CH enabled).")
        self._is_controller_active = True
        self._control_setpoint_override = initial_setpoint
        self._last_keep_alive_time = time.time() # Reset keep-alive timer
        return True

    async def relinquish_control(self):
        """Gives control back to the thermostat by setting CS=0."""
        self.error_manager.log_info("Attempting to relinquish control (CS=0)...")
        status, _ = await self._send_command("CS", 0)
        if status != OTGW_RESPONSE_OK:
            self.error_manager.log_error("Failed to set CS=0. May still be controlling.")
            # Don't change internal state if command failed
            return False
        else:
            self.error_manager.log_info("Successfully relinquished control (CS=0 sent).")
            self._is_controller_active = False
            self._control_setpoint_override = 0.0
            return True

    async def set_control_setpoint(self, temp):
        """Sets the boiler Control Setpoint (ID=1). Requires controller active."""
        if not self._is_controller_active:
            self.error_manager.log_warning("Cannot set Control Setpoint (CS). Controller not active.")
            return False
        if temp < 0 or temp > 90: # Example plausible range, adjust as needed
            self.error_manager.log_warning(f"Control Setpoint {temp} out of plausible range (0-90).")
            # return False # Optional: enforce range check

        status, _ = await self._send_command("CS", temp)
        if status == OTGW_RESPONSE_OK:
            self._control_setpoint_override = float(temp) # Update internal state on success
            return True
        return False

    async def set_dhw_setpoint(self, temp):
        """Sets the Domestic Hot Water setpoint (ID=56)."""
        # This might not require _is_controller_active, depends on boiler/thermostat interaction
        # Check docs: "This command is only effective with boilers that support this function."
        if temp < 0 or temp > 80: # Example plausible range
            self.error_manager.log_warning(f"DHW Setpoint {temp} out of plausible range (0-80).")

        status, _ = await self._send_command("SW", temp)
        return status == OTGW_RESPONSE_OK

    async def set_max_modulation(self, percentage):
         """Sets the Maximum Relative Modulation level (ID=14)."""
         # This might not require _is_controller_active
         if percentage < 0 or percentage > 100:
             self.error_manager.log_warning(f"Max Modulation {percentage} out of range (0-100).")
             return False

         status, _ = await self._send_command("MM", percentage)
         return status == OTGW_RESPONSE_OK

    async def set_central_heating(self, enabled: bool):
        """Enable/disable Central Heating when controller is active (CH=1/0)."""
        if not self._is_controller_active:
            self.error_manager.log_warning("Cannot set Central Heating (CH). Controller not active.")
            return False

        state = 1 if enabled else 0
        status, _ = await self._send_command("CH", state)
        return status == OTGW_RESPONSE_OK

    # --- START: Newly Added Boiler Command Methods ---
    async def set_max_ch_setpoint(self, temp):
        """Sets the Maximum Central Heating water Setpoint (SH command, ID 57)."""
        # Note: Set to 0 to return control to thermostat/boiler.
        # Range check might be needed based on boiler limits (ID 49)
        if temp < 0 or temp > 90: # Example plausible range
            self.error_manager.log_warning(f"Max CH Setpoint {temp} out of plausible range (0-90).")
            # Consider adding check against ID 49 values if available

        status, _ = await self._send_command("SH", temp)
        return status == OTGW_RESPONSE_OK

    async def set_control_setpoint_2(self, temp):
        """Sets the boiler Control Setpoint for 2nd CH circuit (C2 command, ID 8). Requires controller active(?)."""
        # OTGW docs imply C2 requires periodic refresh like CS, assume controller active needed.
        if not self._is_controller_active:
            self.error_manager.log_warning("Cannot set Control Setpoint 2 (C2). Controller not active.")
            return False
        if temp < 0 or temp > 90: # Example plausible range
            self.error_manager.log_warning(f"Control Setpoint 2 {temp} out of plausible range (0-90).")

        status, _ = await self._send_command("C2", temp)
        if status == OTGW_RESPONSE_OK:
            self._control_setpoint2_override = float(temp) # Update internal state
            return True
        return False

    async def set_central_heating_2(self, enabled: bool):
        """Enable/disable Central Heating for 2nd circuit when C2 is active (H2 command)."""
        # Assume controller active needed as it relates to C2
        if not self._is_controller_active:
            self.error_manager.log_warning("Cannot set Central Heating 2 (H2). Controller not active.")
            return False

        state = 1 if enabled else 0
        status, _ = await self._send_command("H2", state)
        return status == OTGW_RESPONSE_OK

    async def set_ventilation_setpoint(self, percentage):
        """Sets the Relative Ventilation Setpoint (VS command, ID 71)."""
        if percentage < 0 or percentage > 100:
             self.error_manager.log_warning(f"Ventilation Setpoint {percentage} out of range (0-100).")
             return False
        # Use 'T' or other non-numeric to clear override, but method expects int
        status, _ = await self._send_command("VS", percentage)
        return status == OTGW_RESPONSE_OK

    async def reset_boiler_counter(self, counter_name):
        """Resets a boiler counter (RS command)."""
        valid_counters = ["HBS", "HBH", "HPS", "HPH", "WBS", "WBH", "WPS", "WPH"]
        if counter_name not in valid_counters:
            self.error_manager.log_warning(f"Invalid counter name for RS command: {counter_name}")
            return False
        status, _ = await self._send_command("RS", counter_name)
        return status == OTGW_RESPONSE_OK

    # --- END: Newly Added Boiler Command Methods ---

    async def set_hot_water_mode(self, state):
         """Control DHW mode (HW=0/1/P/other)."""
         # Valid states: 0, 1, 'P', or other char to reset to thermostat control
         if not isinstance(state, (int, str)) or (isinstance(state, str) and len(state) != 1):
             self.error_manager.log_warning(f"Invalid HW state: {state}. Use 0, 1, 'P', or other single char.")
             return False
         if isinstance(state, int) and state not in (0, 1):
             self.error_manager.log_warning(f"Invalid HW state: {state}. Use 0 or 1 for integer state.")
             return False

         status, _ = await self._send_command("HW", state)
         return status == OTGW_RESPONSE_OK

    # --- Status Methods ---
    def get_status(self):
        """Returns the dictionary of currently known status data."""
        # Consider returning a deep copy if modification by caller is a concern
        return self._status_data

    def get_last_response(self, cmd_code):
        """Returns the last received response string for a command code."""
        return self._last_responses.get(cmd_code)

    def is_active(self):
        """Returns True if the controller is currently overriding the thermostat."""
        return self._is_controller_active

    # --- Specific Status Getters ---
    def _get_parsed_value(self, data_id):
        """Internal helper to safely get parsed value for a Data ID."""
        data = self._status_data.get(data_id)
        if data and 'parsed_value' in data:
            return data['parsed_value']
        return None

    def get_control_setpoint(self):
        """Returns the last known Control Setpoint (ID 1, f8.8) or None."""
        return self._get_parsed_value(1)

    def get_master_status_flags(self):
        """Returns the dictionary of master status flags (ID 0, HB) or None."""
        status_0 = self._get_parsed_value(0)
        return status_0.get('master') if isinstance(status_0, dict) else None

    def get_slave_status_flags(self):
        """Returns the dictionary of slave status flags (ID 0, LB) or None."""
        status_0 = self._get_parsed_value(0)
        return status_0.get('slave') if isinstance(status_0, dict) else None

    def is_ch_enabled(self):
        """Returns True if Master Status indicates CH Enable is set, False otherwise."""
        flags = self.get_master_status_flags()
        return flags.get("CH Enable", 0) == 1 if flags else False

    def is_dhw_enabled(self):
        """Returns True if Master Status indicates DHW Enable is set, False otherwise."""
        flags = self.get_master_status_flags()
        return flags.get("DHW Enable", 0) == 1 if flags else False

    def is_cooling_enabled(self):
        """Returns True if Master Status indicates Cooling Enable is set, False otherwise."""
        flags = self.get_master_status_flags()
        return flags.get("Cooling Enable", 0) == 1 if flags else False

    def is_fault_present(self):
        """Returns True if Slave Status indicates Fault Indication is set, False otherwise."""
        flags = self.get_slave_status_flags()
        return flags.get("Fault Indication", 0) == 1 if flags else False

    def is_flame_on(self):
        """Returns True if Slave Status indicates Flame Status is set, False otherwise."""
        flags = self.get_slave_status_flags()
        return flags.get("Flame Status", 0) == 1 if flags else False

    def get_fault_flags(self):
        """Returns the dictionary of fault flags (ID 5, LB) or None."""
        status_5 = self._get_parsed_value(5)
        return status_5.get('flags') if isinstance(status_5, dict) else None

    def get_oem_fault_code(self):
        """Returns the OEM fault code (ID 5, HB) or None."""
        status_5 = self._get_parsed_value(5)
        return status_5.get('oem_code') if isinstance(status_5, dict) else None

    def get_max_relative_modulation(self):
        """Returns the last known Max Relative Modulation Level (ID 14, f8.8) or None."""
        return self._get_parsed_value(14)

    def get_room_setpoint(self):
        """Returns the last known Room Setpoint (ID 16, f8.8) or None."""
        return self._get_parsed_value(16)

    def get_relative_modulation(self):
        """Returns the last known Relative Modulation Level (ID 17, f8.8) or None."""
        return self._get_parsed_value(17)

    def get_ch_water_pressure(self):
        """Returns the last known CH Water Pressure (ID 18, f8.8) or None."""
        return self._get_parsed_value(18)

    def get_room_temperature(self):
        """Returns the last known Room Temperature (ID 24, f8.8) or None."""
        return self._get_parsed_value(24)

    def get_boiler_water_temp(self):
        """Returns the last known Boiler Water Temperature (ID 25, f8.8) or None."""
        return self._get_parsed_value(25)

    def get_dhw_temperature(self):
        """Returns the last known DHW Temperature (ID 26, f8.8) or None."""
        return self._get_parsed_value(26)

    def get_outside_temperature(self):
        """Returns the last known Outside Temperature (ID 27, f8.8) or None."""
        return self._get_parsed_value(27)

    def get_return_water_temp(self):
        """Returns the last known Return Water Temperature (ID 28, f8.8) or None."""
        return self._get_parsed_value(28)

    def get_dhw_setpoint(self):
        """Returns the last known DHW Setpoint (ID 56, f8.8) or None."""
        return self._get_parsed_value(56)

    def get_max_ch_water_setpoint(self):
        """Returns the last known Max CH Water Setpoint (ID 57, f8.8) or None."""
        return self._get_parsed_value(57)

    # --- Newly added getters ---
    def get_control_setpoint_2(self):
        """Returns the last known Control Setpoint for 2nd CH circuit (ID 8, f8.8) or None."""
        return self._get_parsed_value(8)

    def get_ventilation_setpoint(self):
        """Returns the last known Ventilation Setpoint (ID 71, u8) or None."""
        # Corresponds to V/H control setpoint in PS=1 output
        return self._get_parsed_value(71)

    # --- Parsing Helpers ---
    def _parse_f88(self, hb, lb):
        """Parses OpenTherm f8.8 format (signed fixed-point)."""
        value = (hb << 8) | lb
        # Check sign bit (MSB of hb)
        if hb & 0x80:
            # Negative value, compute two's complement
            value = -( ( (~value) + 1 ) & 0xFFFF )
        return value / 256.0

    def _parse_u16(self, hb, lb):
        """Parses OpenTherm u16 format (unsigned integer)."""
        return (hb << 8) | lb

    def _parse_s8(self, byte_val):
        """Parses OpenTherm s8 format (signed char)."""
        if byte_val & 0x80:
            return -( ( (~byte_val) + 1 ) & 0xFF )
        return byte_val

    def _parse_bitfield(self, byte_val, flag_map):
        """Parses a byte into a dictionary of named flags based on a mapping."""
        flags = {}
        for bit_pos, flag_name in flag_map.items():
            flags[flag_name] = (byte_val >> bit_pos) & 1
        return flags

    # Add more parsing helpers as needed for specific data types 