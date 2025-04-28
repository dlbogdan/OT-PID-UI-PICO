# Core imports
import ujson as json
# import network
import time
# import os
import gc
# import socket
import errno
# import _thread # No longer needed for get_ident here
import asyncio # <<< ADDSYNCIO IMPORT

from managers.manager_logger import Logger

logger = Logger()


try:
    import ssl as tls # Standard library name
except ImportError:
    try:
        import ussl as tls # MicroPython name
    except ImportError:
        print("Warning: No SSL module found. HTTPS connections will fail.")
        tls = None
# define __debug__ flag

# --- Custom Network Exception ---
class NetworkError(OSError):
    """Custom exception for critical network errors."""
    pass
# --- End Custom Exception ---

# --- JSON-RPC Client ---
class JsonRpcClient:
    """Handles sending JSON-RPC requests over HTTP/HTTPS using asyncio."""

    DEFAULT_HEADERS = {"Content-Type": "application/json",
                       "User-Agent": "PicoW-AsyncJsonRpcClient/1.0"}

    def __init__(self, base_url, timeout=15, headers=None):
        self.base_url = base_url
        self.timeout = timeout # Timeout in seconds
        self.headers = headers if headers is not None else self.DEFAULT_HEADERS
        self._session_id = None # Managed externally

        # Parse URL parts (remains synchronous)
        try:
            self.proto, _, self.host, self.path_prefix = base_url.split("/", 3)
            self.path_prefix = "/" + self.path_prefix
        except ValueError:
            self.proto, _, self.host = base_url.split("/", 2)
            self.path_prefix = "/"

        self.port = 443 if self.proto == "https:" else 80
        if ":" in self.host:
            self.host, port_str = self.host.split(":", 1)
            self.port = int(port_str)

        self.is_https = (self.proto == "https:")
        if self.is_https and tls is None:
             raise RuntimeError("HTTPS requested but no SSL/TLS module found.")

        logger.info(f"AsyncJsonRpcClient initialized for: {self.base_url} (Host: {self.host}, Port: {self.port}, HTTPS: {self.is_https})")


    # --- Make _urlopen ASYNCHRONOUS ---
    async def _urlopen(self, method, path, data=None):
        """Internal ASYNC method to perform the actual HTTP/HTTPS request."""
        reader = None
        writer = None
        start_urlopen = time.ticks_ms()
        logger.trace(f"Async _urlopen: Starting request to {self.host}:{self.port}{path}{data}")

        try:
            # --- Use asyncio streams ---
            # print(f"Async _urlopen: Opening connection...") # Debug
            connect_coro = asyncio.open_connection(self.host, self.port)
            # Apply timeout to the connection attempt
            reader, writer = await asyncio.wait_for(connect_coro, timeout=self.timeout)
            # print(f"Async _urlopen: Connection established.") # Debug

            # HTTPS doesn't work for now 
            # not sure if it's worth the trouble to get it working
            #todo

            # if self.is_https:
            #     # print(f"Async _urlopen: Wrapping connection for SSL...") # Debug
            #     # Create SSL context (synchronous part)
            #     ssl_context = tls.SSLContext(tls.PROTOCOL_TLS_CLIENT)
            #     ssl_context.verify_mode = tls.CERT_NONE # WARNING: Insecure for public sites
            #     # Wrap the stream (asynchronous part might occur internally)
            #     # The server_hostname is important for SNI
            #     wrap_coro = asyncio.start_server(None, reader=reader, writer=writer, ssl=ssl_context, server_hostname=self.host)
            #     # Note: start_server seems odd here, but it's how MicroPython docs sometimes show client wrapping
            #     # There might be a simpler way depending on the exact asyncio implementation version
            #     # Alternatively, low-level ssl_handshake might be needed if start_server isn't right.
            #     # Let's assume this works for now, might need adjustment.
            #     # A timeout on the wrapping/handshake might also be wise.
            #     # THIS PART IS THE MOST LIKELY TO NEED ADJUSTMENT BASED ON MPY VERSION
            #     # For now, let's rely on the overall request timeout. If connection wraps but handshake hangs, timeout should trigger later.
            #     # A simpler approach might be needed if start_server isn't intended for clients.
            #     print("WARNING: SSL wrapping method in asyncio might need verification/adjustment.")
            #     # Let's skip the explicit await on start_server for now and proceed.
            #     # If SSL fails, it will likely error during write/read.

            # --- Send Request ---
            # print(f"Async _urlopen: Sending request...") # Debug
            writer.write(f"{method} {path} HTTP/1.0\r\n".encode())
            writer.write(f"Host: {self.host}\r\n".encode())
            for key, value in self.headers.items():
                writer.write(f"{key}: {value}\r\n".encode())
            if data:
                writer.write(f"Content-Length: {len(data)}\r\n".encode())
            writer.write(b"\r\n")
            if data:
                writer.write(data.encode() if isinstance(data, str) else data)
            await writer.drain() # Ensure data is sent
            # print(f"Async _urlopen: Request sent.") # Debug

            # --- Read Response ---
            # print(f"Async _urlopen: Reading status line...") # Debug
            # Read status line with timeout
            try:
                status_line_bytes = await asyncio.wait_for(reader.readline(), timeout=self.timeout)
            except asyncio.TimeoutError:
                logger.error("Async _urlopen Error: Timeout waiting for status line.")
                raise # Re-raise TimeoutError

            if not status_line_bytes:
                raise OSError("Server closed connection before sending status line.")
            status_line = status_line_bytes.decode().strip()
            # print(f"Async _urlopen: Status Line: {status_line}") # Debug
            parts = status_line.split(" ", 2)
            if len(parts) < 2: raise ValueError(f"Malformed status line: {status_line}")
            status_code = int(parts[1])

            # Read headers
            resp_headers = {}
            while True:
                try:
                    header_line_bytes = await asyncio.wait_for(reader.readline(), timeout=self.timeout)
                except asyncio.TimeoutError:
                    logger.error("Async _urlopen Error: Timeout waiting for headers.")
                    raise # Re-raise TimeoutError
                if not header_line_bytes or header_line_bytes == b'\r\n':
                    break # End of headers
                try:
                    key, value = header_line_bytes.decode().split(":", 1)
                    resp_headers[key.strip().lower()] = value.strip()
                except ValueError: logger.warning(f"Warning: Malformed header line ignored: {header_line_bytes}")
            
            gc.collect() # Optional: Collect garbage after reading headers
            # Read body
            body = b""
            if "content-length" in resp_headers:
                length = int(resp_headers["content-length"])
                read_so_far = 0
                while read_so_far < length:
                    bytes_to_read = min(4096, length - read_so_far)
                    try:
                        chunk = await asyncio.wait_for(reader.read(bytes_to_read), timeout=self.timeout)
                    except asyncio.TimeoutError:
                        logger.error("Async _urlopen Error: Timeout waiting for body chunk.")
                        raise # Re-raise TimeoutError
                    if not chunk: raise OSError("Incomplete response (Content-Length mismatch - EOF)")
                    body += chunk
                    read_so_far += len(chunk)
            elif resp_headers.get("transfer-encoding", "").lower() == "chunked":
                 # Simplified chunked reading - might need more robustness
                 while True:
                     try: chunk_size_line = await asyncio.wait_for(reader.readline(), timeout=self.timeout)
                     except asyncio.TimeoutError: logger.error("Timeout reading chunk size"); raise
                     try: chunk_size = int(chunk_size_line.strip(), 16)
                     except ValueError: raise ValueError(f"Invalid chunk size: {chunk_size_line}")
                     if chunk_size == 0:
                          try: await asyncio.wait_for(reader.readline(), timeout=self.timeout) # Read trailing CRLF
                          except asyncio.TimeoutError: logger.error("Timeout reading chunk trailer"); raise
                          break
                     chunk_data = b""
                     read_so_far = 0
                     while read_so_far < chunk_size:
                         bytes_to_read = min(4096, chunk_size - read_so_far)
                         try: chunk = await asyncio.wait_for(reader.read(bytes_to_read), timeout=self.timeout)
                         except asyncio.TimeoutError: logger.error("Timeout reading chunk data"); raise
                         if not chunk: raise OSError("Incomplete chunk data")
                         chunk_data += chunk
                         read_so_far += len(chunk)
                     try: await asyncio.wait_for(reader.readline(), timeout=self.timeout) # Read CRLF after chunk
                     except asyncio.TimeoutError: logger.error("Timeout reading chunk CRLF"); raise
                     body += chunk_data
            else:
                # Read until EOF (less reliable, use if no length/chunking)
                while True:
                    try:
                        chunk = await asyncio.wait_for(reader.read(1024), timeout=self.timeout)
                    except asyncio.TimeoutError:
                        logger.warning("Async _urlopen Warning: Timeout during read-to-EOF, returning partial body.")
                        break # Return what we have on timeout
                    if not chunk:
                        break # EOF
                    body += chunk

            logger.trace("Async _urlopen: Request finished successfully.")
            return status_code, resp_headers, body.decode()

        # --- Error Handling ---
        except asyncio.TimeoutError:
            logger.error(f"AsyncJsonRpcClient Error: Request timed out after {self.timeout}s (overall or during specific read/write)")
            raise NetworkError("Request Timeout")
        except OSError as e:
            # Handle specific connection errors etc.
            errno_val = e.args[0]
            # Check for critical network errors and raise specific exception
            critical_errnos = (
                errno.ECONNREFUSED, 
                errno.EHOSTUNREACH, 
                errno.ECONNABORTED, 
                errno.ECONNRESET,
                # errno.ENETUNREACH # Removed as may not be present
            )
            if errno_val in critical_errnos:
                logger.error(f"AsyncJsonRpcClient Error: Critical Network OSError: {e}")
                raise NetworkError(e) # Raise specific exception
            else:
                # For other OS errors, return a generic server error status
                logger.warning(f"AsyncJsonRpcClient Warning: Non-critical OSError during urlopen: {e}")
                return 500, {}, f"Network Error: {e}"
        except Exception as e:
            logger.error(f"AsyncJsonRpcClient Error: Unexpected error during urlopen: {e}")
            import sys
            sys.print_exception(e)
            return 500, {}, f"Internal Client Error: {e}"
        finally:
            # --- Ensure streams are closed ---
            if writer:
                # print(f"Async _urlopen: Closing writer stream...") # Debug
                writer.close()
                try:
                    await writer.wait_closed() # Wait for close to complete
                except Exception as close_e:
                    logger.error(f"Async _urlopen: Error during writer.wait_closed: {close_e}") # Log error but continue
                # print(f"Async _urlopen: Writer stream closed.") # Debug
            # Reader is implicitly closed when writer is closed for sockets in asyncio
            # print(f"Async _urlopen: Method finished in {time.ticks_diff(time.ticks_ms(), start_urlopen)} ms.") # Debug
            gc.collect()


    # --- Make request ASYNCHRONOUS ---
    async def request(self, jsonrpc_method, params=None, id_val=1, retries=3, backoff_factor=0.5):
        """Makes an ASYNC JSON-RPC request with retries and exponential backoff."""
        payload = {
            "jsonrpc": "2.0",
            "method": jsonrpc_method,
            "id": id_val
        }
        if params is not None:
            payload["params"] = params

        payload_json = json.dumps(payload)
        logger.trace(f"Async RPC Request > Method: {jsonrpc_method}, ID: {id_val}")

        attempt = 0
        while True:
            attempt += 1
            # Await the async urlopen
            status_code, _, body = await self._urlopen("POST", self.path_prefix, data=payload_json)

            if status_code == 200:
                try:
                    response_data = json.loads(body)
                    if "error" in response_data and response_data["error"]:
                        logger.error(f"Async JsonRpcClient Error: Received JSON-RPC error: {response_data['error']}")
                    logger.trace(f"Async RPC Response < ID: {id_val}, Status: {status_code}")
                    return response_data # Success or RPC-level error contained within
                except ValueError:
                    logger.error(f"Async JsonRpcClient Error: Response status 200 but body is not valid JSON.")
                    logger.error(f"Response body sample: {body[:100]}") # Print sample
                
                    # Treat as failure, potentially retry
            else:
                logger.error(f"Async JsonRpcClient Error: HTTP status {status_code}.")
                # Decide if this status code warrants a retry (e.g., 5xx errors)

            # --- Retry Logic ---
            if attempt >= retries:
                logger.error(f"Async JsonRpcClient Error: Request failed after {attempt} attempts.")
                return None # Max retries reached

            wait_time = backoff_factor * (2 ** (attempt - 1))
            logger.info(f"Retrying in {wait_time:.2f} seconds...")
            await asyncio.sleep(wait_time) # Use async sleep
            gc.collect()
