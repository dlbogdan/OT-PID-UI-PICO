from machine import UART
from hardware_config import OT_UART_ID, OT_UART_TX_PIN, OT_UART_RX_PIN, OT_UART_BAUDRATE
import time
import uasyncio as asyncio
from manager_error import ErrorManager

error_manager = ErrorManager()
DEBUG = error_manager.get_debuglevel()

class OpenthermUARTDriver:
    def __init__(self, periodic_update_interval_ms: int = 55000): # Default to 55 seconds
        self.uart = UART(OT_UART_ID, baudrate=OT_UART_BAUDRATE, tx=OT_UART_TX_PIN, rx=OT_UART_RX_PIN)
        self.uart.init(OT_UART_BAUDRATE, bits=8, parity=None, stop=1)
        self.periodic_update_interval_ms = periodic_update_interval_ms
        self._do_periodic_update = False
        self._periodic_task = None
        self._periodic_heating_setpoint = None # Store the last set CS value
        self._last_periodic_send_time = None

    def close(self):
        self.stop_periodic_update() # Ensure task is stopped before deinit
        self.uart.deinit()
    
    def start_periodic_update(self):
        if not self._periodic_task:
            self._do_periodic_update = True
            self._last_periodic_send_time = time.ticks_ms() # Initialize time
            self._periodic_task = asyncio.create_task(self._run_periodic_update())
            print("[OT Driver] Periodic update task started.")
        else:
            print("[OT Driver] Periodic update task already running.")

    def stop_periodic_update(self):
        self._do_periodic_update = False
        if self._periodic_task:
            try:
                self._periodic_task.cancel()
                print("[OT Driver] Periodic update task cancelled.")
            except asyncio.CancelledError:
                pass # Expected
            except Exception as e:
                 error_manager.log_error(f"Error cancelling periodic task: {e}")
            self._periodic_task = None
        # Optional: Log the stop action
        # error_manager.log_info("OpenthermUARTDriver: Periodic updates stopped.")

    async def _run_periodic_update(self):
        if DEBUG>=1:
            print("[OT Driver] Running periodic update loop...")
        loop_count = 0
        while self._do_periodic_update:
            try:
                loop_count += 1
                current_time = time.ticks_ms()
                time_diff = time.ticks_diff(current_time, self._last_periodic_send_time) if self._last_periodic_send_time is not None else -1
                
                # Diagnostic print before the check
                if loop_count % 20 == 0: # Print roughly every 10 seconds (500ms sleep)
                    if DEBUG>=2:
                        print(f"[OT Periodic Check #{loop_count}] do_update={self._do_periodic_update}, setpoint={self._periodic_heating_setpoint}, last_send={self._last_periodic_send_time}, diff={time_diff}, interval={self.periodic_update_interval_ms}")

                # Check if interval has passed AND if we have a setpoint to send
                if self._periodic_heating_setpoint is not None and \
                   self._last_periodic_send_time is not None and \
                   time_diff >= self.periodic_update_interval_ms:
                    
                    if DEBUG>=1:
                        print(f"[OT Driver Task] Condition MET. Sending periodic CS={self._periodic_heating_setpoint:.2f}") # Log before sending
                    # Use _send_command directly to avoid immediate resend loop in set_boiler_control_setpoint
                    self._send_command("CS", self._periodic_heating_setpoint)
                    if DEBUG>=2:
                        print(f"[OT Driver Task] Sent CS={self._periodic_heating_setpoint:.2f}")
                    self._last_periodic_send_time = current_time # Update last send time
                
                # Sleep for a short duration before checking again
                # Adjust sleep time based on desired responsiveness vs resource usage
                await asyncio.sleep_ms(500) 
            except asyncio.CancelledError:
                print("[OT Driver] Periodic update task loop cancelled.")
                self._do_periodic_update = False # Ensure loop condition breaks
                break # Exit loop
            except Exception as e:
                error_manager.log_error(f"Error in OT periodic update loop: {e}")
                await asyncio.sleep(5) # Wait longer after error
        print("[OT Driver] Periodic update loop finished.")

    def _send_command(self, command_prefix: str, value: float):
        """Helper to format and send a command like XX=value\\r"""
        command = f"{command_prefix}={value:.2f}\r"
        if DEBUG>=2:
            print(f"[OTGW] Sending: {command.strip()}") # Debug print similar to C++ version
        #self.uart.write(command.encode('ascii'))
        self.uart.write(command.encode('ascii'))


    def relinquish_control(self):
        """Sends CS=0\\r command to relinquish control."""
        self.stop_periodic_update()
        self._send_command("CS", 0)
        self._send_command("CH", 0)
        if DEBUG>=1:
            print(f"[OT Driver] Relinquished control")

    def takeover_control(self):
        """Sends CH=1\\r command to take control over the heating."""
        # self._send_command("CS", 17)
        self.start_periodic_update()
        self._send_command("CH", 1)
        if DEBUG>=1:
            print(f"[OT Driver] Took over control")
    

    def disable_heating(self):
        """Sends CS=10\\r command to disable heating."""
        self.stop_periodic_update()
        self._send_command("CS", 10)
        self._send_command("CH", 0)
        if DEBUG>=1:
            print(f"[OT Driver] Disabled heating")

    def enable_heating(self):
        self.start_periodic_update()
        self._send_command("CH", 1)
        if DEBUG>=1:
            print(f"[OT Driver] Enabled heating")   

    def set_boiler_max_setpoint(self, max_setpoint: float):
        """Sends SH=<temp>\\r command."""
        self._send_command("SH", max_setpoint)
        if DEBUG>=1:
            print(f"[OT Driver] Set boiler max setpoint to {max_setpoint:.2f}")


    def set_heating_control_setpoint(self, control_setpoint: float):
        """Sends CS=<temp>\r command immediately and stores it for periodic updates."""
        self._periodic_heating_setpoint = control_setpoint # Store for periodic task
        # Reset timer if we manually send, so periodic doesn't send immediately after
        self._last_periodic_send_time = time.ticks_ms()
        self._send_command("CS", control_setpoint) # Send immediately
        if DEBUG>=1:
            print(f"[OT Driver] Set heating control setpoint to {control_setpoint:.2f}")

    def set_dhw_control_setpoint(self, control_setpoint: float):
        """Sends TD=<temp>\\r command."""
        self._send_command("SW", control_setpoint)
        if DEBUG>=1:
            print(f"[OT Driver] Set dhw control setpoint to {control_setpoint:.2f}")

    async def read_response(self, timeout_ms: int = 1000):
        """
        Reads and parses a line from the OpenTherm Gateway asynchronously.
        Uses polling with timeout for async compatibility.

        Returns:
            tuple: (type, value) where type is 'SH', 'CS', 'ERROR', 'OTHER', or 'TIMEOUT'.
                   value is the parsed float for 'SH'/'CS', the error code string for 'ERROR',
                   the raw response string for 'OTHER', or None for 'TIMEOUT'.
        """
        print(f"[OTGW] Reading response...")
        start_time = time.ticks_ms()
        line_bytes = b''
        while time.ticks_diff(time.ticks_ms(), start_time) < timeout_ms:
            if self.uart.any() > 0:
                # Read one byte at a time to ensure we find \r correctly
                byte_read = self.uart.read(1)
                if byte_read:
                    line_bytes += byte_read
                    # Check if we have a complete line (terminated by '\r')
                    if byte_read == b'\r':
                        break # Found end of line
            
            # Yield control to the scheduler if no data or line incomplete
            await asyncio.sleep_ms(1) 

        # Check if loop ended due to timeout or finding a line
        if not line_bytes or line_bytes[-1:] != b'\r':
            #print("[OTGW] Read timeout or incomplete line.")
            # Consider returning partial data if needed: ('OTHER', line_bytes)
            return ('TIMEOUT', None)

        # --- Processing logic --- 
        try:
            # Decode and strip whitespace (including the trailing \r)
            line = line_bytes.decode('ascii').strip()
        except UnicodeError:
            print(f"[OTGW] Received non-ASCII data: {line_bytes}")
            return ('OTHER', line_bytes) # Return raw bytes if decode fails

        if not line:
             # Handle empty lines if necessary
            return ('OTHER', '')

        # if DEBUG>=2:
        print(f"[OTGW] Received: {line}") # Debug print

        if line.startswith("SH:"):
            try:
                val_str = line[3:].strip()
                val_float = float(val_str)
                if DEBUG>=2:
                    print(f"[OTGW] Max CH setpoint accepted: {val_float:.2f}")
                return ('SH', val_float)
            except ValueError:
                if DEBUG>=2:
                    print(f"[OTGW] Error parsing SH value: {line}")
                return ('OTHER', line)
        elif line.startswith("CS:"):
            try:
                val_str = line[3:].strip()
                val_float = float(val_str)
                if DEBUG>=2:
                    print(f"[OTGW] Current CH setpoint override accepted: {val_float:.2f}")
                return ('CS', val_float)
            except ValueError:
                if DEBUG>=2:
                    print(f"[OTGW] Error parsing CS value: {line}")
                return ('OTHER', line)
        elif len(line) == 2:
            error_codes = {
                "NG": "Unknown command",
                "SE": "Syntax error",
                "BV": "Bad value",
                "OR": "Out of range",
                "NS": "No space",
                "NF": "Not found",
                "OE": "Overrun error"
            }
            if line in error_codes:
                print(f"[OTGW] Error: {error_codes[line]} ({line}).")
                return ('ERROR', line)
            else:
                print(f"[OTGW] Unrecognized 2-char code: {line}")
                return ('ERROR', line) # Treat unrecognized 2-char as error type
        else:
            if DEBUG>=2:
                print(f"[OTGW] Other response: {line}")
            return ('OTHER', line)



class OpenthermController:
    def __init__(self, ot_driver: OpenthermUARTDriver, max_heating_setpoint: float):
        self._ot_max_heating_setpoint = max_heating_setpoint
        self.ot_current_heating_setpoint = 60
        self.ot_current_dhw_setpoint = 60
        self.ot_driver = ot_driver
        # Internal state for last response
        self.last_response_type = None
        self.last_response_value = None
        self.last_read_time = None
        self._is_connected = False
        self._is_heating_enabled = False
        self._is_dhw_enabled = False
        self._is_control_enabled = False
        self._manual_heating = False
        self._manual_heating_setpoint = 55.0

        self.ot_driver.disable_heating()
        self.ot_driver.relinquish_control()

    # Properties to access/modify internal state
    @property
    def controller_enabled(self):
        return self._is_control_enabled
    
    @controller_enabled.setter
    def controller_enabled(self, value):
        if value and not self._is_control_enabled:
            self.enable_controller_internal()
        elif not value and self._is_control_enabled:
            self.disable_controller_internal()
    
    @property
    def heating_enabled(self):
        return self._is_heating_enabled
    
    @heating_enabled.setter
    def heating_enabled(self, value):
        if value and not self._is_heating_enabled:
            self.enable_heating_internal()
        elif not value and self._is_heating_enabled:
            self.disable_heating_internal()
    
    @property
    def dhw_enabled(self):
        return self._is_dhw_enabled
    
    @dhw_enabled.setter
    def dhw_enabled(self, value):
        if value and not self._is_dhw_enabled:
            self.enable_dhw_internal()
        elif not value and self._is_dhw_enabled:
            self.disable_dhw_internal()
    
    @property
    def manual_heating(self):
        return self._manual_heating
    
    @manual_heating.setter
    def manual_heating(self, value):
        self._manual_heating = value
        if value and self._is_control_enabled:
            self.set_heating_setpoint(self._manual_heating_setpoint)
    
    @property
    def manual_heating_setpoint(self):
        return self._manual_heating_setpoint
    
    @manual_heating_setpoint.setter
    def manual_heating_setpoint(self, value):
        self._manual_heating_setpoint = value
        if self._manual_heating and self._is_control_enabled:
            self.set_heating_setpoint(value)
            
    @property
    def dhw_setpoint(self):
        return self.ot_current_dhw_setpoint
    
    @dhw_setpoint.setter
    def dhw_setpoint(self, value):
        self.set_dhw_setpoint(value)
        
    @property
    def ot_max_heating_setpoint(self):
        return self._ot_max_heating_setpoint
    
    @ot_max_heating_setpoint.setter
    def ot_max_heating_setpoint(self, value):
        self._ot_max_heating_setpoint = value
        self.ot_driver.set_boiler_max_setpoint(value)

    def get_current_heating_setpoint(self):
        return self.ot_current_heating_setpoint
    
    def get_current_dhw_setpoint(self):
        return self.ot_current_dhw_setpoint

    def set_heating_setpoint(self, setpoint: float):
        if not self._is_control_enabled:
            self.ot_driver.takeover_control()
            self._is_control_enabled = True
        
        if not self._is_heating_enabled:
            self.ot_driver.enable_heating()
            self._is_heating_enabled = True
        
        self.ot_current_heating_setpoint = setpoint
        self.ot_driver.set_heating_control_setpoint(setpoint)
        if DEBUG>=1:
            print(f"[OT Controller] Set heating setpoint to {setpoint:.2f}")

    def set_dhw_setpoint(self, setpoint: float):
        if not self._is_control_enabled:
            self.ot_driver.takeover_control()
            self._is_control_enabled = True
        
        if not self._is_dhw_enabled:
            self._is_dhw_enabled = True
        
        self.ot_current_dhw_setpoint = setpoint
        self.ot_driver.set_dhw_control_setpoint(setpoint)
        if DEBUG>=1:
            print(f"[OT Controller] Set dhw setpoint to {setpoint:.2f}")

    # Internal methods used by property setters
    def enable_dhw_internal(self):      
        self.ot_driver.set_dhw_control_setpoint(self.ot_current_dhw_setpoint)
        self._is_dhw_enabled = True
        if DEBUG>=1:
            print(f"[OT Controller] Enabled dhw")
    
    def enable_heating_internal(self):
        self.ot_driver.set_heating_control_setpoint(self.ot_current_heating_setpoint)
        self._is_heating_enabled = True
        if DEBUG>=1:
            print(f"[OT Controller] Enabled heating")

    def disable_heating_internal(self):
        self.ot_driver.disable_heating()
        self._is_heating_enabled = False
        if DEBUG>=1:
            print(f"[OT Controller] Disabled heating")

    def disable_dhw_internal(self):
        self.ot_driver.set_dhw_control_setpoint(20)  # Low temperature to disable DHW
        self._is_dhw_enabled = False
        if DEBUG>=1:
            print(f"[OT Controller] Disabled dhw")

    def disable_controller_internal(self):
        self.ot_driver.relinquish_control()
        self._is_control_enabled = False
        if DEBUG>=1:
            print(f"[OT Controller] Disabled controller")

    def enable_controller_internal(self):
        self.ot_driver.takeover_control()
        self._is_control_enabled = True
        if DEBUG>=1:
            print(f"[OT Controller] Enabled controller")
        
        # Apply current settings when controller is enabled
        if self._manual_heating:
            self.set_heating_setpoint(self._manual_heating_setpoint)
        
        # Enable heating/DHW based on current flags
        if self._is_heating_enabled:
            self.enable_heating_internal()
        if self._is_dhw_enabled:
            self.enable_dhw_internal()

    # Legacy methods - these call the property setters
    def enable_dhw(self):
        self.dhw_enabled = True
    
    def enable_heating(self):
        self.heating_enabled = True

    def disable_heating(self):
        self.heating_enabled = False

    def disable_dhw(self):
        self.dhw_enabled = False

    def disable_controller(self):
        self.controller_enabled = False

    def enable_controller(self):
        self.controller_enabled = True

    def is_connected(self):
        return self._is_connected
    
    def update_state(self):
        """
        Updates hardware state based on internal configuration.
        This can be called periodically to ensure hardware state matches configuration.
        """
        if self._is_control_enabled:
            self.enable_controller_internal()
            
            if self._manual_heating and self._manual_heating_setpoint != self.ot_current_heating_setpoint:
                self.set_heating_setpoint(self._manual_heating_setpoint)
                
            if self._is_heating_enabled:
                self.enable_heating_internal()
            else:
                self.disable_heating_internal()
                
            if self._is_dhw_enabled:
                self.enable_dhw_internal()
            else:
                self.disable_dhw_internal()
        else:
            self.disable_controller_internal()
    
    async def update(self):
        """
        Reads the next response from the OpenTherm driver and updates internal state.
        Called periodically by the main loop's opentherm_update task.
        """
        # Ensure hardware state matches our internal configuration
        self.update_state()
        
        if not self._is_control_enabled:
            return
            
        try:
            # Read response using the driver
            response_type, response_value = await self.ot_driver.read_response(timeout_ms=1500)
            self.last_read_time = time.ticks_ms()

            if response_type != 'TIMEOUT':
                self._is_connected = True
                self.last_response_type = response_type
                self.last_response_value = response_value
                if response_type == 'ERROR':
                    # Error logging/handling now done within driver's read_response
                    pass 
            else:
                self._is_connected = False

        except Exception as e:
            error_manager.log_error(f"Error in OpenthermController update: {e}")
            self.last_response_type = 'COMM_ERROR'
            self.last_response_value = str(e)
