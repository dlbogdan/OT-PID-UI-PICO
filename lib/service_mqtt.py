import uasyncio as asyncio
# Ensure umqtt.simple is available in your MicroPython environment/libs folder
from umqtt.simple import MQTTClient

import utime as time
import machine # Potentially for unique_id
import ubinascii # Potentially for client_id generation
import json
import gc

# Optional: Placeholder if you integrate a central error manager later
# from manager_error import error_manager

class MQTTClientService:
    """
    Asynchronous MQTT client service for MicroPython using umqtt.simple.
    Handles connection management, dynamic topic subscription/publishing,
    and data marshalling.
    """
    def __init__(self, client_id, server, port=1883, user=None, password=None, keepalive=60, ssl_params=None, error_callback=None):
        """
        Initializes the MQTT Client Service.

        Args:
            client_id: Unique client ID for the MQTT connection. Can be generated e.g. using ubinascii.hexlify(machine.unique_id())
            server: MQTT broker address (IP or hostname).
            port: MQTT broker port.
            user: Username for MQTT authentication (optional).
            password: Password for MQTT authentication (optional).
            keepalive: Keepalive interval in seconds. MQTT PINGREQ will be sent roughly at keepalive/2 interval.
            ssl_params: Dictionary of SSL parameters for secure connections (optional).
            error_callback: Optional function to call with error messages (e.g., error_manager.log_error)
        """
        if MQTTClient is None:
             raise RuntimeError("umqtt.simple library not found or failed to import.")

        self.client_id = client_id
        self.server = server
        self.port = port
        self.user = user
        self.password = password
        self.keepalive = keepalive
        self.ssl_params = ssl_params if ssl_params else {}
        self.error_callback = error_callback

        self.client: MQTTClient | None = None

        # Topic Management:
        # _listener_topics: {topic_str: {'type': type_str, 'qos': int}}
        self._listener_topics: dict[str, dict] = {}
        # _publisher_topics: {topic_str: {'type': type_str, 'qos': int, 'value': object, 'dirty': bool, 'retain': bool}}
        self._publisher_topics: dict[str, dict] = {}

        # Data Storage for listened topics: {topic_str: value}
        self._listened_data: dict[str, object] = {}

        # State Management
        self._is_connected: bool = False
        self._last_ping_sent: int = 0
        self._last_ping_received: int = 0 # Track PINGRESP or any incoming packet
        self._reconnect_delay_ms: int = 5000  # Initial reconnect delay
        self._connection_attempts: int = 0
        self._lock = asyncio.Lock() # Protect client access during operations - still needed for connect/update

    def _log_error(self, message: str):
        """Logs an error message using the provided callback or prints it."""
        if self.error_callback:
            try:
                self.error_callback(f"MQTT Error: {message}")
            except Exception as e:
                print(f"Error calling MQTT error callback: {e}")
                print(f"Original MQTT Error: {message}") # Fallback print
        else:
            print(f"MQTT Error: {message}")

    def _log_info(self, message: str):
        """Logs an info message (currently just prints)."""
        # Add callback later if needed
        print(f"MQTT Info: {message}")

    def _log_warning(self, message: str):
        """Logs a warning message (currently just prints)."""
        # Add callback later if needed
        print(f"MQTT Warning: {message}")


    def _mqtt_callback(self, topic: bytes, msg: bytes):
        """Internal callback for handling received MQTT messages."""
        try:
            topic_str = topic.decode('utf-8')
            msg_str = msg.decode('utf-8')
            # self._log_info(f"RX: T='{topic_str}', M='{msg_str}'") # Debug

            if topic_str in self._listener_topics:
                config = self._listener_topics[topic_str]
                value_type = config.get('type', 'str')
                value: object = None # Use object as a generic type hint

                try:
                    if not msg_str: # Handle empty messages gracefully
                        value = None
                    elif value_type == 'int':
                        value = int(msg_str)
                    elif value_type == 'float':
                        value = float(msg_str)
                    elif value_type == 'bool':
                        # Handle various boolean representations
                        value = msg_str.lower() in ('true', '1', 'yes', 'on', 't', 'y')
                    elif value_type == 'json':
                        value = json.loads(msg_str)
                    else: # Default to string
                        value = msg_str

                    # Store data without lock - reading thread-safe usually, writing needs care
                    # Potential minor race condition if get() is called exactly as value is updated
                    # but acceptable for many use cases. Add lock if strict consistency needed.
                    self._listened_data[topic_str] = value
                    # print(f"MQTT Parsed: T='{topic_str}', V='{value}' ({type(value)})") # Debug
                except ValueError as e:
                    self._log_error(f"Parse Error (ValueError): T='{topic_str}', M='{msg_str}', Type='{value_type}', E={e}")
                except Exception as e:
                    self._log_error(f"Parse Error (Other): T='{topic_str}', M='{msg_str}', E={e}")
            else:
                 self._log_warning(f"RX for unmanaged topic '{topic_str}'")

            # Any message received resets the ping response timer
            self._last_ping_received = time.ticks_ms()
            gc.collect() # Collect garbage after processing message

        except Exception as e:
             self._log_error(f"Callback critical error: {e}")


    def add_listener(self, topic: str, value_type: str = 'str', qos: int = 0):
        """
        Registers a topic to subscribe to. Re-subscribes on reconnect.
        This method is synchronous and modifies internal state. Subscription happens on connect/reconnect.

        Args:
            topic: The MQTT topic string.
            value_type: Expected data type ('str', 'int', 'float', 'bool', 'json'). Affects parsing in callback.
            qos: Quality of Service level (0 or 1). umqtt.simple supports QoS 0 and 1.
        """
        # No lock needed here as it modifies dicts before connect/async ops start typically
        # Or if called later, worst case is a slight delay if connect is happening concurrently
        if topic not in self._listener_topics:
            self._log_info(f"Registering Listener: T='{topic}', Type='{value_type}', QoS={qos}")
            self._listener_topics[topic] = {'type': value_type, 'qos': qos}
            self._listened_data.setdefault(topic, None) # Initialize data storage

            # Attempt immediate subscribe only if already connected (requires lock)
            # This is less critical now, connect() handles initial subs
            # We might add a separate async method `resubscribe_topic` if needed later.


    def add_publisher(self, topic: str, value_type: str = 'str', initial_value: object = None, qos: int = 0, retain: bool = False):
        """
        Registers a topic that this client can publish messages to.
        This method is synchronous. Publishing happens in the async update loop.

        Args:
            topic: The MQTT topic string.
            value_type: Data type hint ('str', 'int', 'float', 'bool', 'json'). Used for serialization.
            initial_value: An initial value to set (optional). If provided, it will be published on first connect.
            qos: Quality of Service level (0 or 1).
            retain: Whether messages on this topic should be retained by the broker.
        """
        # No lock needed for the same reasons as add_listener
        if topic not in self._publisher_topics:
            self._log_info(f"Registering Publisher: T='{topic}', Type='{value_type}', QoS={qos}, Retain={retain}")
            self._publisher_topics[topic] = {
                'type': value_type,
                'qos': qos,
                'value': initial_value,
                'dirty': initial_value is not None, # Mark dirty if initial value provided
                'retain': retain
            }

    def get(self, topic: str) -> object:
        """
        Retrieves the last known value received for a subscribed topic. Synchronous.

        Args:
            topic: The MQTT topic string.

        Returns:
            The last received value, or None if the topic is not listened to
            or no message has been received yet.
        """
        # Reading self._listened_data without a lock. See comment in _mqtt_callback.
        return self._listened_data.get(topic, None)

    def set(self, topic: str, value: object):
        """
        Sets the value for a registered publisher topic, marking it to be sent on the next update cycle.
        Synchronous method. The actual publish is async.

        Args:
            topic: The MQTT topic string (must be registered via add_publisher).
            value: The value to be published.
        """
        # No lock needed here. Modifies dict value and flag.
        # The async 'update' loop reads this state within a lock.
        if topic in self._publisher_topics:
            config = self._publisher_topics[topic]
            # Optional: Add type validation/conversion here if desired based on config['type']
            if config['value'] != value:
                config['value'] = value
                config['dirty'] = True
                # print(f"MQTT Set: T='{topic}', V='{value}', Marked dirty.") # Debug
        else:
            self._log_warning(f"Set called for unregistered publisher topic '{topic}'")

    # --- Async Methods ---

    async def connect(self) -> bool:
        """Attempts to establish a connection to the MQTT broker. Async."""
        # Prevent concurrent connection attempts
        async with self._lock:
            if self._is_connected: # Check inside lock
                 return True

            self._connection_attempts += 1
            self._log_info(f"Connecting: Attempt {self._connection_attempts} to {self.server}:{self.port} as {self.client_id}...")
            gc.collect() # Free memory before connection attempt

            try:
                # Clean up previous client instance if necessary
                if self.client:
                    try:
                        # disconnect() can block or raise errors, ignore during cleanup
                        pass
                    except Exception:
                        pass
                    self.client = None
                    gc.collect()

                # Create the MQTT client instance
                assert self.ssl_params is not None, "SSL parameters are required"
                
                self.client = MQTTClient(
                    client_id=self.client_id.encode('utf-8'),
                    server=self.server,
                    port=self.port,
                    user=self.user.encode('utf-8') if self.user else None,
                    password=self.password.encode('utf-8') if self.password else None,
                    keepalive=self.keepalive,
                    ssl=bool(self.ssl_params),
                    ssl_params=self.ssl_params
                )
                assert self.client is not None, "MQTTClient object creation failed"
                self.client.set_callback(self._mqtt_callback)

                # Set last will (LWT) - BEFORE connect()
                lwt_topic = f"clients/{self.client_id}/status"
                lwt_msg = b"offline"
                self._log_info(f"Setting LWT: T='{lwt_topic}', M='{lwt_msg.decode('utf-8')}'")
                self.client.set_last_will(lwt_topic.encode('utf-8'), lwt_msg, retain=True, qos=1)

                # Perform the connection (blocking call within async task)
                await asyncio.sleep_ms(100) # Short pause
                self.client.connect() # Raises OSError on failure
                await asyncio.sleep_ms(200) # Short pause

                # --- Connection Successful ---
                self._is_connected = True
                self._reconnect_delay_ms = 5000  # Reset reconnect delay
                self._connection_attempts = 0
                self._log_info(f"Connected: Server={self.server}:{self.port}")

                # Subscribe to all registered listener topics
                self._log_info("Subscribing (initial/reconnect):")
                for topic, config in self._listener_topics.items():
                    qos = config['qos']
                    self._log_info(f"  - Subscribing to T='{topic}', QoS={qos}")
                    try:
                        assert self.client is not None
                        self.client.subscribe(topic.encode('utf-8'), qos=qos)
                        await asyncio.sleep_ms(50) # Small delay between subs
                    except Exception as e:
                        self._log_error(f"Subscribe Error (initial): T='{topic}', E={e}")
                        # Consider impact: connection remains, but topic isn't subscribed.

                # Mark all publisher topics with initial values as dirty
                published_initial_status = False
                for topic, config in self._publisher_topics.items():
                    if config['value'] is not None and topic != lwt_topic: # Don't force initial LWT publish
                         # Only mark dirty, let update loop publish
                         config['dirty'] = True
                         # self._log_info(f"Marked initial value dirty for: T='{topic}'")

                # Publish initial 'online' status immediately after connect if registered
                if lwt_topic in self._publisher_topics:
                     self._log_info(f"Publishing initial status: T='{lwt_topic}', M='online'")
                     # Use internal publish method directly, bypassing dirty flag for immediate publish
                     await self._publish_now_internal(lwt_topic, "online", self._publisher_topics[lwt_topic]['qos'], self._publisher_topics[lwt_topic]['retain'])
                     published_initial_status = True
                     # Mark this topic clean now
                     self._publisher_topics[lwt_topic]['dirty'] = False

                # Reset ping timers
                self._last_ping_sent = time.ticks_ms()
                self._last_ping_received = time.ticks_ms()
                gc.collect()
                return True

            except OSError as e:
                self._log_error(f"Connection Error (OSError): {e}")
                self.client = None # Ensure client object is cleared
                self._is_connected = False
                self._reconnect_delay_ms = min(self._reconnect_delay_ms * 2, 60000) # Exponential backoff
                self._log_info(f"Increasing reconnect delay to {self._reconnect_delay_ms / 1000:.1f}s")
                gc.collect()
                return False
            except Exception as e:
                self._log_error(f"Connection Error (Other): {e}")
                self.client = None
                self._is_connected = False
                self._reconnect_delay_ms = min(self._reconnect_delay_ms * 2, 60000)
                self._log_info(f"Increasing reconnect delay to {self._reconnect_delay_ms / 1000:.1f}s")
                gc.collect()
                return False

    async def disconnect(self):
        """Gracefully disconnects from the MQTT broker. Async."""
        # Lock needed to prevent concurrent disconnect/update operations
        async with self._lock:
            if not self._is_connected or not self.client:
                return # Already disconnected or no client

            self._log_info("Disconnecting...")
            try:
                # Publish 'offline' status explicitly if desired, LWT handles unexpected disconnects
                # lwt_topic = f"clients/{self.client_id}/status"
                # if lwt_topic in self._publisher_topics:
                #    await self._publish_now_internal(lwt_topic, "offline", qos=1, retain=True)
                #    await asyncio.sleep_ms(100) # Allow time for publish

                assert self.client is not None
                self.client.disconnect() # Blocking call
            except Exception as e:
                self._log_error(f"Disconnect Error: {e}")
            finally:
                # Ensure state is updated even if disconnect call fails
                self.client = None
                self._is_connected = False
                self._connection_attempts = 0 # Reset attempts on intentional disconnect
                self._log_info("Disconnected.")
                gc.collect()

    def is_connected(self) -> bool:
        """Returns the current connection status. Synchronous."""
        return self._is_connected

    def _serialize_payload(self, value: object) -> bytes:
        """Converts Python types to bytes suitable for MQTT payload. Synchronous."""
        if isinstance(value, bytes):
            return value
        elif isinstance(value, (dict, list, tuple)):
            try:
                return json.dumps(value, separators=(',', ':')).encode('utf-8')
            except Exception as e:
                self._log_error(f"JSON Error: Could not serialize {value}: {e}")
                return str(value).encode('utf-8') # Fallback
        elif isinstance(value, bool):
            return b'true' if value else b'false'
        elif isinstance(value, (int, float)):
             return str(value).encode('utf-8')
        elif value is None:
            return b'' # Empty payload for None
        else: # Default to string conversion
            return str(value).encode('utf-8')

    async def _publish_now_internal(self, topic: str, value: object, qos: int, retain: bool):
        """Internal unlocked method to perform the actual publish action. Async."""
        # Assumes connection check and client existence check happened *before* call (within lock)
        assert self.client is not None, "_publish_now_internal called with no client"
        try:
            payload = self._serialize_payload(value)
            payload_str_preview = payload.decode('utf-8')[:50] + ('...' if len(payload) > 50 else '')
            # self._log_info(f"TX: T='{topic}', P='{payload_str_preview}', QoS={qos}, Retain={retain}") # Debug
            self.client.publish(topic.encode('utf-8'), payload, retain=retain, qos=qos)
            # If publish succeeded, update the last sent time
            self._last_ping_sent = time.ticks_ms()
            return True
        except OSError as e:
             self._log_error(f"Publish Error (OSError): T='{topic}', E={e}. Assuming disconnect.")
             raise e # Re-raise OSError to trigger disconnect/reconnect in update loop
        except Exception as e:
            self._log_error(f"Publish Error (Other): T='{topic}', E={e}")
            return False # Indicate publish failed but connection might still be ok

    async def update(self):
        """
        Asynchronous task loop for MQTT operations. Handles incoming messages,
        publishing, keepalives, and connection management.
        Should be run continuously using asyncio.create_task().
        """
        self._log_info("Update Task Started")
        while True:
            if not self._is_connected:
                # Attempt to reconnect if disconnected
                self._log_info(f"Connection down. Attempting reconnect in {self._reconnect_delay_ms / 1000:.1f}s...")
                await asyncio.sleep_ms(self._reconnect_delay_ms)
                await self.connect() # connect() handles lock and state updates internally
                continue # Skip rest of loop iteration, check connection status again next time

            # --- If connected ---
            current_time = time.ticks_ms()
            acquired_lock = False
            try:
                # Lock needed for MQTT client operations (check_msg, publish, ping)
                await self._lock.acquire()
                acquired_lock = True

                # Re-check connection status after acquiring lock
                if not self._is_connected or not self.client:
                    continue # Connection lost just before lock acquired

                assert self.client is not None, "Client missing in update loop despite lock+connected"

                # 1. Check for Incoming Messages (can raise OSError)
                # self._log_info("Checking messages...") # Verbose Debug
                self.client.check_msg()
                # If check_msg succeeded, reset ping response timer. Callback also resets it.
                self._last_ping_received = time.ticks_ms()

                # 2. Publish Dirty Topics
                # Iterate over a copy of keys in case dict is modified elsewhere (unlikely)
                topics_to_publish = list(self._publisher_topics.keys())
                for topic in topics_to_publish:
                    if topic in self._publisher_topics: # Re-check existence
                        config = self._publisher_topics[topic]
                        if config['dirty']:
                            # Pass client explicitly or assert inside publish method
                            if await self._publish_now_internal(topic, config['value'], config['qos'], config['retain']):
                                config['dirty'] = False # Mark clean ONLY if publish succeeded
                            else:
                                # Publish failed (non-OSError), keep dirty and retry.
                                self._log_warning(f"Failed to publish dirty topic '{topic}', will retry.")

                # 3. Keep-alive Ping
                # Send PINGREQ if no packet sent/received recently and half keepalive time passed
                # Check if time since last *sent* packet >= keepalive/2
                if time.ticks_diff(current_time, self._last_ping_sent) >= (self.keepalive * 500): # keepalive/2 in ms
                     # Send PINGREQ (can raise OSError)
                     # self._log_info("Sending PINGREQ") # Debug
                     self.client.ping()
                     self._last_ping_sent = current_time # Reset time after successful ping

                # 4. Check for Activity Timeout (Ping Response / Incoming Data)
                # If keepalive time passes without *any* incoming activity, assume connection lost
                # Use 1.5x tolerance for network latency
                if time.ticks_diff(current_time, self._last_ping_received) > (self.keepalive * 1500): # keepalive * 1.5 in ms
                     self._log_error(f"No activity/PINGRESP received within {self.keepalive * 1.5:.1f}s (Keepalive: {self.keepalive}s).")
                     raise OSError("MQTT Activity Timeout") # Treat as connection error

            except OSError as e:
                self._log_error(f"Update Error (OSError): {e}. Triggering disconnect.")
                # Force disconnect state; connection attempt will happen next loop cycle
                self.client = None # Ensure client object is cleared
                self._is_connected = False
                gc.collect()
                # Continue to start of loop for reconnect logic without delay
                continue # Skips the sleep at the end
            except Exception as e:
                self._log_error(f"Update Error (Other): {e}")
                # Add a small delay to prevent tight loops on persistent non-OS errors.
                await asyncio.sleep_ms(2000)
            finally:
                if acquired_lock:
                    self._lock.release()

            # Yield control - sleep outside the lock
            await asyncio.sleep_ms(100) # Main loop check interval (adjust as needed)
            gc.collect() # Periodic garbage collection


# --- Example Usage (Illustrative - requires async context) ---
async def example_mqtt_usage():
    print("Starting MQTT example...")
    # Generate a unique client ID
    client_id = ubinascii.hexlify(machine.unique_id()).decode('utf-8')
    print(f"Using MQTT Client ID: {client_id}")

    # --- Configuration ---
    MQTT_BROKER = "your_broker_ip_or_hostname" # REPLACE
    MQTT_PORT = 1883
    MQTT_USER = None # or "your_username"
    MQTT_PASSWORD = None # or "your_password"
    # ---------------------

    if MQTT_BROKER == "your_broker_ip_or_hostname":
        print("!!! MQTT Broker not configured. Skipping example run. !!!")
        return


    mqtt_service = MQTTClientService(
        client_id=client_id,
        server=MQTT_BROKER,
        port=MQTT_PORT,
        user=MQTT_USER,
        password=MQTT_PASSWORD,
        keepalive=60, # 60 seconds keepalive
        error_callback=print # Simple error printing
    )

    # Register listeners and publishers (synchronous calls)
    base_topic = f"devices/{client_id}"
    mqtt_service.add_listener(f"{base_topic}/command", value_type='str', qos=1)
    mqtt_service.add_listener("sensors/outside/temperature", value_type='float')
    mqtt_service.add_publisher(f"{base_topic}/status", value_type='str', initial_value='online', qos=1, retain=True)
    mqtt_service.add_publisher(f"{base_topic}/sensor/value", value_type='int', qos=0)
    mqtt_service.add_publisher(f"{base_topic}/config", value_type='json', qos=1)


    # Start the main MQTT update task in the background
    print("Creating MQTT update task...")
    mqtt_task = asyncio.create_task(mqtt_service.update())
    print("MQTT update task created.")


    counter = 0
    while True:
        # --- Interaction Example ---
        # Get received data (synchronous)
        command = mqtt_service.get(f"{base_topic}/command")
        if command is not None:
            print(f"Received command: {command}")
            # Process command...
            # Clear command after processing? mqtt_service.set(f"{base_topic}/command", None)? Risky if retains.
            # Better to have command act on state, and maybe publish an ack/status change.
            mqtt_service.set(f"{base_topic}/command", "") # Clear the command topic state if not retained

        outside_temp = mqtt_service.get("sensors/outside/temperature")
        if outside_temp is not None:
            print(f"Outside Temperature: {outside_temp:.1f} C")


        # Set data to be published (synchronous - marks dirty)
        mqtt_service.set(f"{base_topic}/sensor/value", counter)
        if counter % 10 == 0: # Publish config less often
             mqtt_service.set(f"{base_topic}/config", {"interval": 10, "enabled": True})
             # print(f"Set config to publish: {{'interval': 10, 'enabled': True}}")

        print(f"MQTT Connected: {mqtt_service.is_connected()}, Loop: {counter}, MemFree: {gc.mem_free()}")

        counter += 1
        await asyncio.sleep(5) # Main application loop interval

# To run the example:
# import uasyncio
# uasyncio.run(example_mqtt_usage()) 