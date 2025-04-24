import uasyncio
from machine import UART, Pin
import time
import platform_spec as cfg
from managers.manager_logger import Logger

logger = Logger()
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

DEFAULT_CONTROL_SETPOINT = 10.0 # Default setpoint if no override is set

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
BOILER_TIMEOUT_S = 60 # Seconds without a boiler message to be considered disconnected

class OpenThermController():
    """
    Asynchronous controller for an OpenTherm Gateway (OTGW) via UART.
    """
    def __init__(self, uart:UART):
        self.uart = uart   
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
        self._last_fault_present_state = 0 # Track previous fault state, initialize to 0 (no fault)
        self._last_boiler_message_time = 0 # Timestamp of the last message received from the boiler

        # --- New state variables ---
        self._gateway_version = None
        self._thermostat_connected = None # True, False, or None if status unknown
        # --- End new state variables ---

        logger.info("OpenThermController initialized.")

    async def _uart_reader(self):
        """Task to continuously read and parse lines from OTGW."""
        logger.info("OTGW UART reader task started.")
        READ_TIMEOUT_S = 5 # Seconds to wait for a line before assuming timeout
        while True:
            line = "" # Ensure line is defined in case of early exit
            try:
                # Add explicit timeout to readline
                line_bytes = await uasyncio.wait_for(self.stream.readline(), timeout=READ_TIMEOUT_S)

                if not line_bytes:
                    await uasyncio.sleep_ms(50) # Avoid busy-waiting if nothing received
                    continue

                # Decode and strip standard whitespace
                line = line_bytes.decode('ascii').strip()

                # Explicitly skip if line is empty AFTER stripping
                if not line: # or len(line) == 0
                    continue

                logger.debug(f"OTGW RX: {line}") # DEBUG (Keep this standard log)

                # --- Message Parsing ---
                # Check for command response first (XX: Data)
                parts = line.split(':', 1)
                if len(parts) == 2 and len(parts[0]) == 2 and parts[0].isupper():
                    cmd_code = parts[0]
                    response_data = parts[1].strip()
                    logger.info(f"Recognized command response for {cmd_code}: {response_data}")
                    self._last_responses[cmd_code] = response_data
                    if cmd_code in self._response_events:
                        self._response_events[cmd_code].set() # Signal waiting command
                    else:
                        logger.warning(f"Received unsolicited/unexpected response: {line}")

                # Check for specific informational messages using 'in' to handle prepended garbage
                elif "OpenTherm Gateway " in line:
                    # Attempt to extract version robustly, assuming it's the last part
                    try:
                        version_part = line.split("OpenTherm Gateway ")[-1]
                        self._gateway_version = version_part.strip()
                        logger.info(f"Detected OTGW Version: {self._gateway_version} (from line: '{line}')")
                    except Exception:
                        logger.warning(f"Found 'OpenTherm Gateway ' but failed to extract version from: '{line}'")
                elif "Thermostat disconnected" in line:
                    self._thermostat_connected = False
                    logger.warning(f"Thermostat reported disconnected (from line: '{line}')")
                elif "Thermostat connected" in line: # Anticipate this message
                    self._thermostat_connected = True
                    logger.info(f"Thermostat reported connected (from line: '{line}')")

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
                             # Log the specific error here for clarity
                             logger.warning(f"Could not parse OTGW hex status message: {line}")
                    # OTGW Internal Error (e.g., E01)
                    elif msg_source == 'E':
                         logger.error(f"OTGW reported error: {line}")
                    # Other malformed T/B/R/A/E message?
                    else:
                         # This branch now correctly catches things like "Thermostat disconnected" if the elif above failed
                         logger.warning(f"Received unparseable OTGW status/error line (Source={msg_source}): {line}")

                # If it's none of the above known formats
                else:
                    # Only log as unknown if it wasn't handled
                    logger.warning(f"Received unknown format line from OTGW: '{line}'")

            except uasyncio.TimeoutError:
                 logger.warning(f"Timeout waiting for line from OTGW (timeout={READ_TIMEOUT_S}s).")
                 continue
            except Exception as e:
                # Log the line that caused the error, if available
                logger.error(f"Error in OTGW UART reader processing line '{line}': {e}")
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
                # --- Check for Fault Indication change ---
                if isinstance(parsed_value.get('slave'), dict):
                    current_fault_state = parsed_value['slave'].get('Fault Indication')
                    # Check if fault state is known and comes from the Boiler
                    if source == 'B' and current_fault_state is not None:
                        # Trigger PM=5 request if the fault state changed (0->1 or 1->0)
                        if current_fault_state != self._last_fault_present_state:
                             logger.info(
                                 f"Fault Indication changed from {self._last_fault_present_state} to {current_fault_state} (Boiler). Requesting ID 5.")
                             # Run request in background, don't block parser
                             uasyncio.create_task(self.request_priority_message(5))

                             # Update last known state *after* detecting the change
                             self._last_fault_present_state = current_fault_state
                        #else: # State hasn't changed, no need to update or request PM=5 again
                        #    pass
                # --- End Fault Check ---

            elif data_id == 5: # Fault Flags & OEM Code
                 parsed_value = {
                     'oem_code': val_hb, # Store OEM code as raw byte
                     'flags': self._parse_bitfield(val_lb, OT_FAULT_FLAGS_LB)
                 }
            elif data_id in [1, 7, 8, 14, 16, 17, 18, 19, 23, 24, 25, 26, 27, 28, 31, 56, 57]: # f8.8 values
                parsed_value = self._parse_f88(val_hb, val_lb)
            elif data_id == 33: # s16 (Boiler exhaust temperature)
                value = raw_value
                if val_hb & 0x80:
                    value = -( ( (~value) + 1 ) & 0xFFFF )
                parsed_value = value
            elif data_id in [48, 49]: # HB/LB Boundaries (s8)
                parsed_value = {
                    'lower': self._parse_s8(val_lb),
                    'upper': self._parse_s8(val_hb)
                }
            elif data_id == 70: # V/H Control Status flags - Add mapping if needed
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

            # Update boiler message timestamp if source is Boiler
            if source == 'B':
                self._last_boiler_message_time = self._status_data[data_id]['timestamp']

        except Exception as e:
            logger.error(f"Error parsing Data ID {data_id} (HB:{val_hb}, LB:{val_lb}): {e}")
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
        logger.info("OTGW keep-alive task started.")
        while True:
            await uasyncio.sleep(KEEP_ALIVE_INTERVAL)
            if self._is_controller_active:
                now = time.time()
                resend_needed = False
                # Check if CS override needs periodic refresh
                if self._control_setpoint_override >= 8.0:
                     logger.info("Keep-alive: Resending CS command.")
                     await self._send_command("CS", self._control_setpoint_override, timeout=5)
                     resend_needed = True

                # Check if C2 override needs periodic refresh
                if self._control_setpoint2_override >= 8.0:
                    logger.info("Keep-alive: Resending C2 command.")
                    await self._send_command("C2", self._control_setpoint2_override, timeout=5)
                    resend_needed = True

                if resend_needed:
                    self._last_keep_alive_time = now # Update time only if command sent

    async def _send_command(self, cmd_code, value, timeout=2):
        """Sends a command and waits for a specific response."""
        if len(cmd_code) != 2 or not cmd_code.isupper():
            logger.error(f"Invalid command code format: {cmd_code}")
            return OTGW_RESPONSE_SE, None

        async with self._command_lock:
            # Use only carriage return as terminator, per OTGW docs
            cmd_str = f"{cmd_code}={value}\r"
            logger.info(f"OTGW TX: {cmd_str.strip()}")

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
                logger.warning(f"Timeout waiting for response to command: {cmd_code}")
                return OTGW_RESPONSE_TIMEOUT, None
            except Exception as e:
                logger.error(f"Error sending command {cmd_code}: {e}")
                return OTGW_RESPONSE_UNKNOWN, None
            finally:
                # Clean up the event for this specific command instance
                if cmd_code in self._response_events:
                    del self._response_events[cmd_code]


    async def start(self):
        """Starts the background reader and keep-alive tasks."""
        if self._reader_task is None:
            self._reader_task = uasyncio.create_task(self._uart_reader())
            logger.info("Scheduled OTGW UART reader task.")
        else:
            logger.warning("OTGW reader task already started.")

        if self._keep_alive_task is None:
             self._keep_alive_task = uasyncio.create_task(self._keep_alive())
             logger.info("Scheduled OTGW keep-alive task.")
        else:
             logger.warning("OTGW keep-alive task already started.")


    async def stop(self):
        """Stops the background tasks."""
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except uasyncio.CancelledError:
                pass
            self._reader_task = None
            logger.info("OTGW UART reader task stopped.")

        if self._keep_alive_task:
             self._keep_alive_task.cancel()
             try:
                 await self._keep_alive_task
             except uasyncio.CancelledError:
                 pass
             self._keep_alive_task = None
             logger.info("OTGW keep-alive task stopped.")

        # Close UART? Maybe not, allow restarting
        # await self.writer.aclose()
        # self.uart.deinit()

    # --- Control Methods ---

    async def take_control(self):
        """
        Takes control from the thermostat by setting CS and CH.
        Returns tuple (success: bool, message: str).
        """

        if self._control_setpoint_override > 0:
            initial_setpoint = self._control_setpoint_override
        else:
            initial_setpoint = DEFAULT_CONTROL_SETPOINT
        # if initial_setpoint < 0:
        #      logger.warning("Initial setpoint must be >= 0. Using 10.0.")
        #      initial_setpoint = 10.0

        logger.info(f"Attempting to take control with CS={initial_setpoint}...")
        status_cs, resp_cs = await self._send_command("CS", initial_setpoint)
        if status_cs != OTGW_RESPONSE_OK:
            msg = f"Failed to set initial CS (Status: {status_cs}, Resp: {resp_cs})"
            logger.error(msg)
            return False, msg

        status_ch, resp_ch = await self._send_command("CH", 1)
        if status_ch != OTGW_RESPONSE_OK:
            msg = f"Failed to enable CH=1 (Status: {status_ch}, Resp: {resp_ch})"
            logger.error(msg)
            # Still considered partial success if CS was set?
            # Or should we return False here too? For simplicity, let's proceed.
            # To rollback: await self.relinquish_control()

        logger.info("Successfully took control (CS set, CH enabled).")
        self._is_controller_active = True
        self._control_setpoint_override = initial_setpoint
        self._last_keep_alive_time = time.time()
        return True, "Control taken successfully."

    async def relinquish_control(self):
        """Gives control back to thermostat (CS=0). Returns (status_code, response_data)."""
        logger.info("Attempting to relinquish control (CS=0)...")
        status_code, response_data = await self._send_command("CS", 0)
        if status_code == OTGW_RESPONSE_OK:
            logger.info("Successfully relinquished control (CS=0 sent).")
            self._is_controller_active = False
            self._control_setpoint_override = 0.0
            self._control_setpoint2_override = 0.0
        else:
            logger.error(f"Failed to set CS=0 (Status: {status_code}, Resp: {response_data}). May still be controlling.")

        return status_code, response_data

    async def set_control_setpoint(self, temp):
        """Sets CS. Returns (status_code, response_data)."""
        if not self._is_controller_active:
            # Return a specific code or raise an exception? For now, use custom code.
            logger.warning("Cannot set CS. Controller not active.")
            return OTGW_RESPONSE_UNKNOWN + 100, "Controller not active" # Custom code
        if temp < 0 or temp > 90:
            logger.warning(f"Control Setpoint {temp} out of plausible range (0-90).")
            # Allow sending anyway, boiler/gateway might clip it.

        status_code, response_data = await self._send_command("CS", temp)
        if status_code == OTGW_RESPONSE_OK:
            self._control_setpoint_override = float(temp)
        return status_code, response_data

    async def set_dhw_setpoint(self, temp):
        """Sets SW. Returns (status_code, response_data)."""
        if temp < 0 or temp > 80:
            logger.warning(f"DHW Setpoint {temp} out of plausible range (0-80).")
        return await self._send_command("SW", temp)

    async def set_max_modulation(self, percentage):
         """Sets MM. Returns (status_code, response_data)."""
         if percentage < 0 or percentage > 100:
             logger.warning(f"Max Modulation {percentage} out of range (0-100).")
             # Allow sending anyway?
             # return OTGW_RESPONSE_OR, "Percentage out of range"
         return await self._send_command("MM", percentage)

    async def set_central_heating(self, enabled: bool):
        """Sets CH. Returns (status_code, response_data)."""
        if not self._is_controller_active:
            logger.warning("Cannot set CH. Controller not active.")
            return OTGW_RESPONSE_UNKNOWN + 100, "Controller not active" # Custom code
        state = 1 if enabled else 0
        return await self._send_command("CH", state)

    # --- START: Newly Added Boiler Command Methods ---
    async def set_max_ch_setpoint(self, temp):
        """Sets SH. Returns (status_code, response_data)."""
        if temp < 0 or temp > 90:
            logger.warning(f"Max CH Setpoint {temp} out of plausible range (0-90).")
        return await self._send_command("SH", temp)

    async def set_control_setpoint_2(self, temp):
        """Sets C2. Returns (status_code, response_data)."""
        if not self._is_controller_active:
            logger.warning("Cannot set C2. Controller not active.")
            return OTGW_RESPONSE_UNKNOWN + 100, "Controller not active"
        if temp < 0 or temp > 90:
            logger.warning(f"Control Setpoint 2 {temp} out of plausible range (0-90).")

        status_code, response_data = await self._send_command("C2", temp)
        if status_code == OTGW_RESPONSE_OK:
            self._control_setpoint2_override = float(temp)
        return status_code, response_data

    async def set_central_heating_2(self, enabled: bool):
        """Sets H2. Returns (status_code, response_data)."""
        if not self._is_controller_active:
            logger.warning("Cannot set H2. Controller not active.")
            return OTGW_RESPONSE_UNKNOWN + 100, "Controller not active"
        state = 1 if enabled else 0
        return await self._send_command("H2", state)

    async def set_ventilation_setpoint(self, percentage):
        """Sets VS. Returns (status_code, response_data)."""
        if percentage < 0 or percentage > 100:
             logger.warning(f"Ventilation Setpoint {percentage} out of range (0-100).")
             # Allow sending anyway?
             # return OTGW_RESPONSE_OR, "Percentage out of range"
        return await self._send_command("VS", percentage)

    async def reset_boiler_counter(self, counter_name):
        """Sets RS. Returns (status_code, response_data)."""
        valid_counters = ["HBS", "HBH", "HPS", "HPH", "WBS", "WBH", "WPS", "WPH"]
        if counter_name not in valid_counters:
            logger.warning(f"Invalid counter name for RS command: {counter_name}")
            return OTGW_RESPONSE_BV, "Invalid counter name"
        return await self._send_command("RS", counter_name)

    async def request_priority_message(self, data_id):
        """Sets PM. Returns (status_code, response_data)."""
        if not isinstance(data_id, int) or not (0 <= data_id <= 255):
            logger.warning(f"Invalid Data ID for PM command: {data_id}")
            return OTGW_RESPONSE_BV, "Invalid Data ID"
        return await self._send_command("PM", data_id)

    # --- END: Newly Added Boiler Command Methods ---

    async def set_hot_water_mode(self, state):
         """Sets HW. Returns (status_code, response_data)."""
         if not isinstance(state, (int, str)) or (isinstance(state, str) and len(state) != 1):
             logger.warning(f"Invalid HW state: {state}. Use 0, 1, 'P', or other single char.")
             return OTGW_RESPONSE_BV, "Invalid state value"
         if isinstance(state, int) and state not in (0, 1):
             logger.warning(f"Invalid HW state: {state}. Use 0 or 1 for integer state.")
             return OTGW_RESPONSE_BV, "Invalid state value"
         return await self._send_command("HW", state)

    # --- Thermostat Override Commands ---
    async def set_temporary_room_setpoint_override(self, temp):
        """Sets TT. Returns (status_code, response_data)."""
        if not isinstance(temp, (float, int)) or not (0.0 <= temp <= 30.0):
            logger.warning(f"Invalid temp for TT command (0.0-30.0): {temp}")
            return OTGW_RESPONSE_BV, "Temperature out of range"
        return await self._send_command("TT", f"{temp:.2f}")

    async def set_constant_room_setpoint_override(self, temp):
        """Sets TC. Returns (status_code, response_data)."""
        if not isinstance(temp, (float, int)) or not (0.0 <= temp <= 30.0):
            logger.warning(f"Invalid temp for TC command (0.0-30.0): {temp}")
            return OTGW_RESPONSE_BV, "Temperature out of range"
        return await self._send_command("TC", f"{temp:.2f}")

    async def set_thermostat_clock(self, time_str, day_int):
        """Sets SC. Returns (status_code, response_data)."""
        if not isinstance(day_int, int) or not (1 <= day_int <= 7):
            logger.warning(f"Invalid day for SC command (1-7): {day_int}")
            return OTGW_RESPONSE_BV, "Invalid day"
        if not isinstance(time_str, str) or len(time_str) != 5 or time_str[2] != ':':
             logger.warning(f"Invalid time format for SC command (HH:MM): {time_str}")
             return OTGW_RESPONSE_BV, "Invalid time format"
        # Basic HH:MM validation
        try:
            h, m = map(int, time_str.split(':'))
            if not (0 <= h <= 23 and 0 <= m <= 59):
                 raise ValueError("Hour or minute out of range")
        except ValueError as e:
            logger.warning(f"Invalid time value for SC command: {e}")
            return OTGW_RESPONSE_BV, "Invalid time value"

        value_str = f"{time_str}/{day_int}"
        return await self._send_command("SC", value_str)

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

    def is_boiler_connected(self):
        """Checks if a message from the boiler has been received recently."""
        if self._last_boiler_message_time == 0:
            # Haven't seen any boiler message yet since script start
            # We could maybe infer based on recent T messages, but simple timeout is clearer
            logger.warning("Boiler status unknown: No messages received yet.")
            return False
        return (time.time() - self._last_boiler_message_time) < BOILER_TIMEOUT_S

    # --- New getters ---
    def get_gateway_version(self):
        """Returns the reported gateway version string, or None."""
        return self._gateway_version

    def is_thermostat_connected(self):
        """Returns True if thermostat reported connected, False if disconnected, None if unknown."""
        return self._thermostat_connected
    # --- End new getters ---

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