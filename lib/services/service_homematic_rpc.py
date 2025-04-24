# homematic_service.py - Handles asynchronous Homematic CCU3 communication.
import asyncio
from services.service_async_http import JsonRpcClient, NetworkError
import time
import ujson
from managers.manager_logger import Logger

logger = Logger()

# --- Homematic CCU3 RPC Client ---
class HomematicRPCClient:
    """ASYNC Client for interacting with a Homematic CCU3 via JSON-RPC."""

    def __init__(self, rpc_client: JsonRpcClient, username, password):
        """Initializes the Homematic client."""
        self.rpc_client = rpc_client
        self.username = username
        self.password = password
        self._session_id = None
        self._login_attempts = 0
        self._next_req_id = 1
        # Connection status tracking
        self._last_request_success = None
        self._last_request_time = 0
        self._last_error = None
        logger.info(f"Async HomematicRPCClient initialized for user '{username}'.")

    def is_ccu_connected(self):
        """Returns True if the last request to CCU was successful, False if it failed, None if no request made yet."""
        # If we have a successful request within the last 5 seconds, consider connected
        if self._last_request_success and time.ticks_diff(time.ticks_ms(), self._last_request_time) < 5000:
            return True
        return self._last_request_success

    def is_logged_in(self):
        """Checks if a session ID is currently held."""
        return self._session_id is not None

    async def _make_request(self, method, params=None, id_val=None, retries=1):
        try:
            """Internal ASYNC helper to make authenticated requests, handling re-login."""
            current_session = self._session_id

            if not current_session:
                logger.warning(f"Async HC: Not logged in for '{method}', attempting login.")
                if not await self.login():
                    logger.error(f"Async HC Error: Cannot make request '{method}', login failed.")
                    return None
                current_session = self._session_id

            request_params = {"_session_id_": current_session}
            if params:
                request_params.update(params)

            current_request_id = id_val if id_val is not None else self._next_req_id
            if id_val is None:
                self._next_req_id += 1

            # Make the request
            response = await self.rpc_client.request(method, params=request_params, id_val=current_request_id, retries=retries)
            await self._update_connection_status(response)

            session_expired = False
            if response and "error" in response and response["error"]:
                err_data = response["error"]
                err_msg = str(err_data.get("message", "")).lower() if isinstance(err_data, dict) else str(err_data).lower()
                err_code = err_data.get("code") if isinstance(err_data, dict) else None
                if "session" in err_msg or \
                   "nicht angemeldet" in err_msg or \
                   "not logged in" in err_msg or \
                   "access denied" in err_msg or \
                   err_code == -1:
                    session_expired = True
                    logger.error(f"Async HC: Detected potential session expiry/auth issue (Error: {err_data}). Re-logging in.")
                else:
                    # Other errors don't mean CCU is disconnected
                    await self._update_connection_status(response)

            if session_expired:
                self._session_id = None
                current_session = None

                logger.info("Async HC: Attempting re-login...")
                if await self.login():
                    current_session = self._session_id
                    logger.info(f"Async HC: Re-login successful, retrying request '{method}'...")
                    request_params["_session_id_"] = current_session
                    retry_id = self._next_req_id
                    self._next_req_id += 1
                    response = await self.rpc_client.request(method, params=request_params, id_val=retry_id, retries=1)
                    await self._update_connection_status(response)
                else:
                    logger.error("Async HC Error: Re-login failed after session expiry detection.")
                    return None

            return response
        except Exception as e:
            logger.error("Error making RPC request")
            raise

    async def _update_connection_status(self, response, error=None):
        try:
            """Updates the connection status based on the response or error."""
            if response is not None and isinstance(response, dict):
                # Any valid JSON-RPC response means we're connected
                self._last_request_success = True
                self._last_request_time = time.ticks_ms()
                self._last_error = None
            else:
                # No response or invalid response means disconnected
                self._last_request_success = False
                self._last_request_time = time.ticks_ms()
                self._last_error = error
        except Exception as e:
            logger.error("Error updating connection status")
            raise

    async def login(self):
        """ASYNC Logs into the CCU3 and stores the session ID."""
        logger.info("Async HomematicRPCClient: Attempting login...")
        if not self.username or not self.password:
            logger.error("Async HomematicRPCClient Error: Username or Password not provided.")
            await self._update_connection_status(None, "Missing credentials")
            return False

        payload = {"username": self.username, "password": self.password}
        current_id = 1
        response = await self.rpc_client.request("Session.login", params=payload, id_val=current_id, retries=2)
        
        if response and "result" in response and response["result"] and response.get("id") == current_id:
            self._session_id = response["result"]
            logger.info(f"Async HomematicRPCClient: Login successful. Session ID: ...{self._session_id[-6:]}")
            self._login_attempts = 0
            self._next_req_id = 2
            await self._update_connection_status(response)
            return True
        else:
            logger.error(f"Async HomematicRPCClient Error: Login failed. Response: {response}")
            self._session_id = None
            self._login_attempts += 1
            if self._login_attempts >= 3: 
                logger.error("Async HC Error: Multiple failed login attempts.")
            await self._update_connection_status(response, "Login failed")
            return False

    async def logout(self):
        """ASYNC Logs out of the current CCU3 session."""
        if not self.is_logged_in(): return True

        logger.info("Async HomematicRPCClient: Logging out...")
        payload = {"_session_id_": self._session_id}
        current_id = 0
        # Await the async request
        response = await self.rpc_client.request("Session.logout", params=payload, id_val=current_id, retries=1)

        logout_success = (response and response.get("result") == True and response.get("id") == current_id)

        if logout_success: logger.info("Async HomematicRPCClient: Logout successful.")
        else: logger.warning(f"Async HC Warning: Logout command failed. Response: {response}")

        self._session_id = None
        return logout_success

    # --- Make public API methods ASYNCHRONOUS ---
    async def get_version(self):
        """ASYNC Gets the CCU3 firmware version."""
        response = await self._make_request("CCU.getVersion")
        return response.get("result") if response and "result" in response else None

    async def get_device_ids(self):
        """ASYNC Retrieves all device STRING IDs from CCU3 via Device.listAll."""
        logger.info("Async HC: Fetching device IDs (expects list of strings)...")
        response = await self._make_request("Device.listAll")
        result = response.get("result", []) if response and "result" in response else []
        # Validate... (validation logic remains synchronous)
        if isinstance(result, list) and all(isinstance(item, str) for item in result): return result
        elif isinstance(result, list):
             logger.warning(f"Async HC Warning: Device.listAll not list of strings! Got: {repr(result[:5])}")
             return [item for item in result if isinstance(item, str)]
        else:
             logger.warning(f"Async HC Warning: Device.listAll did not return list! Got: {type(result)}")
             return []

    async def get_device_details(self, device_id_str):
        """ASYNC Gets details for a specific device using its string ID."""
        if not isinstance(device_id_str, str):
             logger.error(f"Async HC Error: get_device_details expects string ID, got {type(device_id_str)}")
             return None
        params = {"id": device_id_str}
        response = await self._make_request("Device.get", params=params)
        result = response.get("result") if response and "result" in response else None
        if result is not None and not isinstance(result, dict):
             logger.warning(f"Async HC Warning: Device.get for ID {device_id_str} not dict. Got: {type(result)}")
             return None
        return result

    async def get_value(self, interface, address, value_key):
         """ASYNC Gets a specific value for a device channel."""
         params = {"interface": interface, "address": address, "valueKey": value_key}
         response = await self._make_request("Interface.getValue", params=params)
         return response.get("result") if response and "result" in response else None

    async def get_valve_position(self, interface, address):
        """ASYNC Convenience method to get the valve position ('LEVEL')."""
        channel_address = f"{address}:1"
        # Await the async get_value
        return await self.get_value(interface, channel_address, "LEVEL")
    
    async def list_all_rooms(self):
        """ASYNC Retrieves all room IDs from CCU3 via Room.listAll."""
        # #disable this method for now
        # return []
        logger.info("Async HC: Fetching room IDs...")
        response = await self._make_request("Room.listAll")
        result = response.get("result", []) if response and "result" in response else []
        # Basic validation: expect a list of strings (IDs)
        if isinstance(result, list) and all(isinstance(item, str) for item in result):
            return result
        else:
            logger.warning(f"Async HC Warning: Room.listAll did not return list of strings! Got: {type(result)}")
            # Attempt to filter strings if it's a list of mixed types
            if isinstance(result, list):
                return [item for item in result if isinstance(item, str)]
            return [] # Return empty list on unexpected type

    async def get_room_details(self, room_id_str):
        """ASYNC Gets details for a specific room using its string ID."""
        # #disable this method for now
        # return None
        if not isinstance(room_id_str, str):
            logger.error(f"Async HC Error: get_room_details expects string ID, got {type(room_id_str)}")
            return None
        params = {"id": room_id_str}
        response = await self._make_request("Room.get", params=params)
        result = response.get("result") if response and "result" in response else None
        # Basic validation: expect a dictionary
        if result is not None and not isinstance(result, dict):
            logger.warning(f"Async HC Warning: Room.get for ID {room_id_str} not dict. Got: {type(result)}")
            return None
        return result

# --- Data Service with Caching ---
CACHE_FILENAME = "hm_device_cache.json" #todo: move to config

class HomematicDataService:
    """
    Handles async communication with Homematic CCU3 via JSON-RPC.
    Provides login management and periodic data fetch for valve devices.
    Uses persistent caching for discovered devices.
    """
    def __init__(self, base_url, username, password, valve_device_type):
        """
        Initialize the Homematic service with the CCU3 API URL and credentials.
        Tries to load the device cache from flash.
        """
        # JSON-RPC client for HTTP requests (async)
        self._rpc = JsonRpcClient(base_url)
        self._hm = HomematicRPCClient(self._rpc, username, password)
        self.valve_device_type = valve_device_type  # e.g. "HmIP-eTRV" for thermostat valves
        # Last fetched data
        self.total_devices = 0
        self.valve_devices = 0
        self.reporting_valves = 0
        self.avg_valve = 0.0
        self.max_valve = 0.0
        # Store the identified valve devices to avoid rediscovery
        self._valve_device_list = None # List of dicts: {'iface': str, 'addr': str, 'room_name': str}
        self.max_valve_room_name = "Unknown" # Room corresponding to max_valve

        # Current fetch task (if any)
        self.ms_between_fetches = 60000  # 1 minute
        self.last_fetch = 0
        self._paused = True  # Flag to indicate if the data is paused
        self._fetch_task = None

        # <<<--- LOAD CACHE ON INIT ---
        self._load_cache()
        # <<<------------------------->

        logger.info("HomematicDataService initialized.")
        if self._valve_device_list is not None:
            logger.info(f"  Loaded {len(self._valve_device_list)} devices from cache.")

    # <<<--- NEW: LOAD CACHE METHOD ---
    def _load_cache(self):
        """Attempts to load the valve device list from the cache file."""
        try:
            with open(CACHE_FILENAME, 'r') as f:
                cached_data = ujson.load(f)
            # Basic validation: Check if it's a list
            if isinstance(cached_data, list):
                # Optional: More thorough validation of list items could be added here
                self._valve_device_list = cached_data
                logger.info(f"Successfully loaded cache from {CACHE_FILENAME}")
            else:
                logger.warning(f"Warning: Cache file {CACHE_FILENAME} contained invalid data (not a list). Ignoring.")
                self._valve_device_list = None
        except OSError: # Catches FileNotFoundError and potentially other FS errors
            logger.warning(f"Cache file {CACHE_FILENAME} not found. Will perform discovery.")
            self._valve_device_list = None
        except ValueError: # Catches JSON decoding errors
            logger.warning(f"Warning: Cache file {CACHE_FILENAME} contained invalid JSON. Ignoring.")
            self._valve_device_list = None
        except Exception as e:
            logger.error(f"Error loading cache file {CACHE_FILENAME}: {e}")
            self._valve_device_list = None
    # <<<--------------------------->

    # <<<--- NEW: SAVE CACHE METHOD ---
    def _save_cache(self, device_list):
        """Saves the provided valve device list to the cache file."""
        if device_list is None: # Don't save if discovery failed
            return
        try:
            with open(CACHE_FILENAME, 'w') as f:
                ujson.dump(device_list, f)
            logger.info(f"Successfully saved {len(device_list)} devices to cache file {CACHE_FILENAME}")
        except OSError as e:
            logger.error(f"Error saving cache file {CACHE_FILENAME}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error saving cache: {e}")
    # <<<--------------------------->

    async def _discover_valve_devices_and_rooms(self):
        """Internal helper to discover valve devices and their rooms.
           Sets self._valve_device_list on success and saves to cache.
           Returns True on success (even if empty), False on communication failure.
        """
        logger.info("HomematicService: Discovering valve devices and rooms...")
        discovered_valves = []
        device_ids = await self._hm.get_device_ids()
        room_ids = await self._hm.list_all_rooms()

        if device_ids is None or room_ids is None:
            logger.error("HomematicService: Failed to retrieve device or room list during discovery")
            self._valve_device_list = None # Ensure cache remains clear
            return False # Indicate discovery failure

        self.total_devices = len(device_ids) # Store total found during discovery

        for device_id in device_ids:
            # Skip irrelevant IDs
            if device_id == "12": continue
            try:
                if int(device_id) < 100: continue
            except ValueError: pass # Non-numeric ID, continue

            details = await self._hm.get_device_details(device_id)
            if not details or not isinstance(details, dict): continue

            dev_type = details.get("type", "")
            dev_addr = details.get("address")
            iface = details.get("interface", "HmIP-RF")

            if dev_addr and self.valve_device_type in dev_type:
                # Found a target valve device, find its room
                room_name = "Unknown"
                found_room = False
                channel_id_to_search = None
                try:
                    numeric_device_id = int(device_id)
                    channel_id_to_search = str(numeric_device_id + 1)
                except ValueError:
                    logger.warning(f"Warning: Could not convert device ID '{device_id}' to int for room search.")

                if channel_id_to_search:
                    for room_id in room_ids:
                        if found_room: break
                        room_details = await self._hm.get_room_details(room_id)
                        if room_details and isinstance(room_details.get('channelIds'), list):
                            if channel_id_to_search in room_details['channelIds']:
                                room_name = room_details.get('name', 'Unnamed Room')
                                found_room = True
                
                discovered_valves.append({
                    'iface': iface,
                    'addr': dev_addr,
                    'room_name': room_name
                })

        # Store the successfully discovered list (even if empty)
        self._valve_device_list = discovered_valves
        logger.info(f"HomematicService: Discovery complete. Found {len(self._valve_device_list)} valve devices.")

        # <<<--- SAVE CACHE AFTER SUCCESSFUL DISCOVERY ---
        self._save_cache(self._valve_device_list)
        # <<<------------------------------------------->

        return True # Indicate discovery success

    def paused(self) -> bool:
        """Returns True if the data is paused."""
        return self._paused
    
    def set_paused(self, paused: bool):
        """Sets the paused state and cancels any ongoing fetch if pausing externally."""
        # Determine if cancellation is needed *before* updating the state
        # Cancel only if transitioning from not paused -> paused
        should_cancel = paused and not self._paused

        if paused != self._paused: # Only act if the state is actually changing
            self._paused = paused # Update the internal state flag
            if paused:
                logger.info("Homematic data fetching paused.")
                if should_cancel: # Check the flag we determined earlier
                    self.cancel_fetch() # Cancel any task potentially running
            else:
                logger.info("Homematic data fetching resumed.")
                # Optionally trigger an immediate fetch check on resume?
                # self.last_fetch = 0

    def update(self):
        if self.paused():
            return  # Skip the update if paused
        
        if not self.paused():
            if not self.is_fetching():
                current_time = time.ticks_ms()
                if time.ticks_diff(current_time, self.last_fetch) > self.ms_between_fetches:
                    self.start_fetch()
                    self.last_fetch = current_time
        else:
            if self.is_fetching():
                self.cancel_fetch()
                self.last_fetch = 0

    def is_ccu_connected(self):
        """Returns True if the last request to CCU was successful, False if it failed, None if no request made yet."""
        return self._hm.is_ccu_connected()

    def start_fetch(self):
        """
        Begin an asynchronous fetch of device data.
        Returns True if a new fetch was started, or False if one is already in progress.
        """
        if self._fetch_task is None or self._fetch_task.done():
            # Launch the fetch_data coroutine as a background task
            self._fetch_task = asyncio.create_task(self.fetch_data())
            return True
        return False

    async def fetch_data(self):
        """
        Async coroutine to fetch all device IDs and valve positions from the CCU3.
        Updates the internal data attributes. Returns True on success, False on error.
        """
        try:
            # Ensure we have a valid session (login if not already logged in)
            if not self._hm.is_logged_in():
                if not await self._hm.login():
                    # Login failed
                    logger.error("HomematicService: Login failed")
                    self._valve_device_list = None # Clear cache on login failure
                    self.reporting_valves = -1
                    return False

            # --- Step 1: Discover devices if cache is empty ---
            if self._valve_device_list is None:
                discovery_success = await self._discover_valve_devices_and_rooms()
                if not discovery_success:
                    # Discovery failed due to communication error
                    self.reporting_valves = -1 # Keep error state
                    return False # Exit fetch_data
                # If discovery succeeded, self._valve_device_list is now populated (or empty)

            # --- Step 2: Process the valve list (fetch LEVELs) ---
            # Use the potentially just-populated or existing cache
            valve_list_to_process = self._valve_device_list

            if valve_list_to_process is None:
                 # Should not happen if discovery logic is correct, but handle defensively
                 logger.error("HomematicService Error: valve_list_to_process is unexpectedly None after discovery check.")
                 self.reporting_valves = -1
                 return False
            
            if not valve_list_to_process: # Discovery succeeded but found 0 devices
                logger.info("HomematicService: No valve devices in list to process.")
                self.valve_devices = 0
                self.reporting_valves = 0
                self.avg_valve = 0.0
                self.max_valve = 0.0
                self.max_valve_room_name = "Unknown"
                return True # Successful fetch (of nothing)

            # If we have devices in the list, proceed to fetch levels
            logger.info(f"HomematicService: Fetching levels for {len(valve_list_to_process)} valve devices...")
            self.valve_devices = len(valve_list_to_process)
            total_position = 0.0
            report_count = 0
            max_position = 0.0
            fetch_error_occurred = False
            current_max_room_name = "Unknown" # Track room for this fetch

            for valve_info in valve_list_to_process: # Iterate through list of dicts
                iface = valve_info['iface']
                dev_addr = valve_info['addr']
                # room_name = valve_info['room_name'] # Available if needed

                pos_str = await self._hm.get_valve_position(iface, dev_addr)
                if pos_str is None:
                    # Error getting value for this device
                    logger.warning(f"HomematicService Warning: Failed to get LEVEL for {iface}/{dev_addr}")
                    fetch_error_occurred = True
                    continue # Skip this device but continue with others
                try:
                    pos_val = float(pos_str)
                except ValueError:
                    logger.warning(f"HomematicService Warning: Invalid LEVEL value '{pos_str}' for {iface}/{dev_addr}")
                    continue # Skip invalid value
                
                total_position += pos_val
                report_count += 1
                if pos_val > max_position:
                    max_position = pos_val
                    current_max_room_name = valve_info['room_name'] # Store room name when max is updated
            
            # Update stats
            self.reporting_valves = report_count
            self.avg_valve = (total_position / report_count) * 100.0 if report_count > 0 else 0.0
            self.max_valve = max_position * 100.0 # Store as percentage
            self.max_valve_room_name = current_max_room_name if report_count > 0 else "Unknown" # Update service attribute

            # If an error occurred fetching any value, clear the cached list for next time
            if fetch_error_occurred:
                logger.warning("HomematicService: Clearing cached valve list due to fetch error(s).")
                self._valve_device_list = None
                # Return False as the data might be incomplete/stale
                return False 
            else:
                return True # Success

        except NetworkError as ne:
            # Specific handling for critical network errors during fetch
            logger.error(f"HomematicService: NetworkError during fetch: {ne}")
            # --- PREVENT SELF-CANCELLATION --- 
            self._paused = True # Set internal flag to prevent new fetches
            # self.set_paused(True) # <- REMOVED THIS CALL that caused the error
            # --- END CHANGE --- 
            self._valve_device_list = None # Clear cache
            self.reporting_valves = -1 # Set error state
            self.max_valve_room_name = "Unknown"
            return False # Indicate failure and let the task end naturally
        except Exception as e:
            logger.error(f"HomematicService: General Exception during fetch_data: {e}")
            # Optional: Consider pausing here too for general errors?
            # self.set_paused(True)
            self._valve_device_list = None # Clear cache on any exception
            self.reporting_valves = -1
            self.max_valve_room_name = "Unknown" # Reset on exception
            return False

    def is_fetching(self):
        """Return True if a fetch task is currently running."""
        return self._fetch_task is not None and not self._fetch_task.done()

    def cancel_fetch(self):
        """Cancel any ongoing fetch task."""
        if self._fetch_task and not self._fetch_task.done():
            self._fetch_task.cancel()
        self._fetch_task = None

    # <<<--- NEW: FORCE RESCAN METHOD ---
    def force_rescan(self):
        """Clears the internal device cache, forcing a rediscovery on the next fetch."""
        logger.info("HomematicService: Force rescan requested. Clearing device cache.")
        self._valve_device_list = None
        # Optionally, reset last_fetch to trigger update sooner?
        # self.last_fetch = 0
    # <<<---------------------------->
