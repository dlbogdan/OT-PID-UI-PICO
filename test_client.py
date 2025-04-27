import socket
import time

# --- Configuration ---
# Should match the server script
SERVER_HOST = 'localhost'
SERVER_PORT = 8123

# --- Client Logic ---
def run_client():
    print(f"--- Test Client Starting ---")
    print(f"Attempting to connect to {SERVER_HOST}:{SERVER_PORT}...")

    client_socket = None
    try:
        while True: # Keep trying to connect
            try:
                client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                client_socket.connect((SERVER_HOST, SERVER_PORT))
                print("Connected successfully!")
                print("Waiting for log messages... (Press Ctrl+C to stop)")
                break # Exit connection loop
            except ConnectionRefusedError:
                print(".", end='', flush=True)
                if client_socket: # Check if socket was created before closing
                    client_socket.close()
                client_socket = None
                time.sleep(1)
            except OSError as e: # Catch broader OSError for other connection issues
                print(f"\nSocket error during connection: {e}")
                if client_socket:
                    client_socket.close()
                return # Exit if other socket error

        if not client_socket:
            print("\nCould not connect after multiple attempts.")
            return

        client_socket.settimeout(1.0) # Set timeout for receiving data

        while True:
            try:
                data = client_socket.recv(1024) # Read up to 1024 bytes
                if not data:
                    print("\nServer disconnected.")
                    break
                # Decode assuming UTF-8 and print, removing potential trailing newline
                message = data.decode('utf-8').strip()
                print(f"Received: {message}")
            except TimeoutError: # Correct exception for socket timeouts
                # No data received within timeout, just continue listening
                continue
            except OSError as e: # Catch other socket errors during receive
                print(f"\nSocket error during receive: {e}")
                break
            except UnicodeDecodeError as e:
                print(f"\nError decoding message: {e} - Data: {data}")
            except KeyboardInterrupt:
                print("\nClient interrupted by user.")
                break

    except KeyboardInterrupt:
         print("\nClient interrupted during connection attempt.")
    finally:
        if client_socket:
            print("Closing client socket.")
            client_socket.close()
        print("--- Test Client Finished ---")

if __name__ == "__main__":
    run_client() 