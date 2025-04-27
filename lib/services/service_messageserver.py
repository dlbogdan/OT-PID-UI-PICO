import uasyncio as asyncio
import usocket

class MessageServer:
    """
    A simple asyncio TCP server to broadcast messages (like logs) to connected clients.
    Handles connections, disconnections, and message sending.
    Prints its own errors to stdout to avoid circular dependencies with the logger.
    """
    def __init__(self, host='0.0.0.0', port=23):
        self._host = host
        self._port = port
        self._clients = [] # List to store active client writers
        self._lock = asyncio.Lock() # To protect access to the _clients list
        self._server = None
        print(f"MessageServer: Initialized to listen on {self._host}:{self._port}")

    async def _handle_connection(self, reader, writer):
        """Callback for new client connections."""
        addr = writer.get_extra_info('peername')
        print(f"MessageServer: Client connected from {addr}")

        async with self._lock:
            self._clients.append(writer)

        try:
            # Keep connection open, primarily waiting for disconnection
            # We don't expect clients to send data, but reading checks the connection
            while True:
                data = await reader.read(1024)
                if not data:
                    # Empty read indicates client disconnected gracefully
                    break
                # Optional: Handle incoming data if needed in the future
                # print(f"MessageServer: Received from {addr}: {data.decode()}")
        except OSError as e:
            print(f"MessageServer: Connection error with {addr}: {e}")
        except Exception as e:
            print(f"MessageServer: Unexpected error with {addr}: {e}")
        finally:
            print(f"MessageServer: Client disconnected: {addr}")
            async with self._lock:
                if writer in self._clients:
                    self._clients.remove(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception as e:
                 print(f"MessageServer: Error closing writer for {addr}: {e}")


    async def run(self):
        """Starts the TCP server."""
        try:
            self._server = await asyncio.start_server(
                self._handle_connection, self._host, self._port
            )
            print(f"MessageServer: Server started successfully on {self._host}:{self._port}")
            # Keep the run task alive while the server runs
            while True:
                await asyncio.sleep(60) # Sleep to prevent busy-waiting
        except OSError as e:
             print(f"MessageServer: Failed to start server on {self._host}:{self._port}: {e}")
             self._server = None # Ensure server object is None if start failed
        except Exception as e:
            print(f"MessageServer: Unexpected error starting server: {e}")
            self._server = None

    # Renamed to async helper
    async def _async_send(self, message):
        """Internal async method to send a message to all connected clients."""
        if not self._server or not self._clients:
            return

        # Add timestamp and newline for Telnet compatibility
        # Using time.ticks_ms() for a monotonic clock, though time.time() might give wall clock if RTC is set
        # Let's stick to a simpler format for now, add timestamp if needed later
        # formatted_message = f"{time.ticks_ms()} - {message}" 
        data = (message + '\r\n').encode('utf-8') # Format and encode here
        disconnected_clients = []

        async with self._lock:
            for writer in list(self._clients): # Iterate over a copy
                try:
                    writer.write(data)
                    await writer.drain()
                except OSError as e:
                    addr = writer.get_extra_info('peername')
                    print(f"MessageServer: Failed to send to {addr}: {e}. Marking for removal.")
                    disconnected_clients.append(writer)
                except Exception as e:
                    addr = writer.get_extra_info('peername')
                    print(f"MessageServer: Unexpected error sending to {addr}: {e}. Marking for removal.")
                    disconnected_clients.append(writer)

            if disconnected_clients:
                # print(f"MessageServer: Removing {len(disconnected_clients)} disconnected client(s).") # Reduce verbosity
                for writer in disconnected_clients:
                    if writer in self._clients:
                        self._clients.remove(writer)
                    try:
                        writer.close()
                        await writer.wait_closed()
                    except Exception:
                        pass

    # Public synchronous method
    def send(self, message):
        """
        Synchronously called method to queue a message for sending to all clients.
        Launches an asynchronous task to handle the actual network operations.
        """
        if not self._server:
            # Don't even create a task if the server isn't running
            return
        # Schedule the async sending without waiting for it
        try:
            asyncio.create_task(self._async_send(message))
        except Exception as e:
            # Catch potential errors during task creation itself
            print(f"MessageServer: Error creating send task: {e}")

    async def stop(self):
        """Stops the server and disconnects clients."""
        print("MessageServer: Stopping server...")
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            print("MessageServer: Server socket closed.")

        async with self._lock:
            print(f"MessageServer: Disconnecting {len(self._clients)} client(s).")
            for writer in self._clients:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass # Ignore errors during forced shutdown
            self._clients.clear()
        print("MessageServer: Server stopped.")

# Example of how it might be used (for testing standalone)
# async def main():
#     server = MessageServer(port=8123)
#     asyncio.create_task(server.run())
#     count = 0
#     while True:
#         await asyncio.sleep(10)
#         count += 1
#         await server.send(f"Server message count: {count}")

# if __name__ == "__main__":
#     try:
#         asyncio.run(main())
#     except KeyboardInterrupt:
#         print("Interrupted")
#         # Proper cleanup would require accessing the server instance and calling stop 