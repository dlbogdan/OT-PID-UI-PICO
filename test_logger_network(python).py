import sys
import asyncio
import time
import json
import os
import os.path # Explicit import for exists
import socket # Explicit import for gaierror

# --- MicroPython Mocking ---
# Create dummy modules to satisfy imports in the library code
class MockMachine:
    def reset(self):
        print("MOCK: machine.reset() called")

class MockUasyncio:
    # Use static methods for module-level functions
    @staticmethod
    async def sleep(secs):
        await asyncio.sleep(secs)

    @staticmethod
    async def sleep_ms(ms):
        await asyncio.sleep(ms / 1000.0)

    @staticmethod
    def create_task(coro):
        return asyncio.create_task(coro)

    # Lock needs to be instantiated. Map the class directly.
    Lock = asyncio.Lock

    @staticmethod
    async def start_server(callback, host, port, backlog=5):
        print(f"MOCK: Wrapping asyncio.start_server(host='{host}', port={port})" )
        # Standard Python asyncio uses keyword args primarily
        return await asyncio.start_server(callback, host=host, port=port, backlog=backlog)

class MockUsocket:
    # Map standard socket constants/functions if needed
    AF_INET = socket.AF_INET # Use standard socket constants
    SOCK_STREAM = socket.SOCK_STREAM
    SOCK_DGRAM = socket.SOCK_DGRAM
    SOL_SOCKET = socket.SOL_SOCKET
    SO_REUSEADDR= socket.SO_REUSEADDR

    # If getaddrinfo is used directly (it is in MessageServer), mock it simply for localhost
    def getaddrinfo(self, host, port, *args):
        # Basic mock for localhost or 0.0.0.0 resolution
        if host == 'localhost' or host == '0.0.0.0' or host == '127.0.0.1':
             # Return format mimics MicroPython's (family, type, proto, canonname, sockaddr)
             # Use constants from the mock class itself or standard socket
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, '', ('127.0.0.1', port))]
        else:
            # Fallback to standard socket for other hosts if needed, or raise error
            # No need to import socket again here
            try:
                return socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
            except socket.gaierror: # Correct exception type should be recognized now
                 print(f"MOCK WARNING: getaddrinfo failed for {host}:{port}")
                 raise OSError(f"Mock getaddrinfo failed for {host}") # Simulate OSError


# Inject mocks before importing project modules
sys.modules['machine'] = MockMachine() # type: ignore
sys.modules['uasyncio'] = MockUasyncio # type: ignore
sys.modules['usocket'] = MockUsocket() # type: ignore

# --- Import Project Code ---
# Now these imports should find the mocks for MicroPython modules
from lib.managers.manager_logger import Logger
from lib.services.service_messageserver import MessageServer

# --- Test Configuration ---
TEST_HOST = 'localhost'
TEST_PORT = 23 # Use a non-standard port to avoid conflicts
LOGGER_FILE = "log.txt"
ERROR_FILE = "lasterror.json"

# --- Test Runner ---
async def main():
    print("--- Starting Network Logger Test ---")
    
    # Clean up previous test files if they exist
    if os.path.exists(LOGGER_FILE): # Correct function name
        os.remove(LOGGER_FILE)
    if os.path.exists(ERROR_FILE): # Correct function name
        os.remove(ERROR_FILE)

    # 1. Initialize Logger (as singleton)
    # Set a higher debug level for testing
    logger = Logger(debug_level=4)
    print(f"Logger instance created: {logger}")

    # 2. Initialize Message Server
    message_server = MessageServer(host=TEST_HOST, port=TEST_PORT)
    print(f"MessageServer instance created: {message_server}")

    # 3. Link Logger and Server
    logger.set_message_server(message_server)
    print("Logger linked with MessageServer")

    # 4. Start the server task
    print(f"Starting MessageServer on {TEST_HOST}:{TEST_PORT}...")
    server_task = asyncio.create_task(message_server.run())
    await asyncio.sleep(0.5) # Give server a moment to start listening

    if not message_server._server:
         print("!!! Server failed to start. Aborting test. !!!")
         return # Exit if server didn't start

    print("--- Server running. Send test messages: ---")
    await asyncio.sleep(10) # Wait for client to connect
    # 5. Send test logs
    while True:
        logger.trace("This is a trace message.")
        # await asyncio.sleep(0.1)
        logger.debug("This is a debug message.")
        # await asyncio.sleep(0.1)
        logger.info("This is an info message.")
        # await asyncio.sleep(0.1)
        logger.warning("This is a warning message.")
        # await asyncio.sleep(0.1)
        logger.error("This is an error message.")
        # await asyncio.sleep(0.1)
        logger.fatal("TestError", "This is a fatal error message.", resetmachine=False)
        # await asyncio.sleep(0.1)
        await asyncio.sleep(2)
    print("--- Test messages sent. Run test_client.py now. ---")
    print("--- Press Ctrl+C to stop the server ---       ")

    try:
        # Keep server running until interrupted
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n--- KeyboardInterrupt received ---       ")
    finally:
        # 6. Cleanup
        print("--- Stopping server and cleaning up ---    ")
        if server_task and not server_task.done():
             if message_server:
                 await message_server.stop()
             # Attempt to cancel the task if stop didn't finish it
             # server_task.cancel()
             # try:
             #      await server_task
             # except asyncio.CancelledError:
             #      print("Server task cancelled.")
        # Clean up log files
        if os.path.exists(LOGGER_FILE): # Correct function name
            # os.remove(LOGGER_FILE)
            print(f"Log file created: {LOGGER_FILE}")
        if os.path.exists(ERROR_FILE): # Correct function name
            # os.remove(ERROR_FILE)
            print(f"Error file created: {ERROR_FILE}")
        print("--- Test finished ---                      ")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError as e:
        # Handle potential asyncio loop errors on exit in some environments
        if "Event loop is closed" in str(e):
             print("Event loop closed gracefully.")
        else:
            raise 