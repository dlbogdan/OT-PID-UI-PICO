import uos
import utime
import machine
import usocket as socket
import ubinascii
import gc
import uasyncio as asyncio
from manager_error import ErrorManager
from manager_wifi import WiFiManager

# Constants
AUTH_USERNAME = "admin"
AUTH_PASSWORD = "otapico"
OTA_PORT = 8080
BUFFER_SIZE = 1024

class OTAUpdateService:
    """Service for Over-The-Air firmware updates via HTTP"""
    
    def __init__(self, wifi_service, auth_username=AUTH_USERNAME, auth_password=AUTH_PASSWORD, port=OTA_PORT):
        """Initialize the OTA update service
        
        Args:
            wifi_service (WiFiManager): WiFi manager instance
            auth_username (str): Basic auth username
            auth_password (str): Basic auth password
            port (int): Port to listen on
        """
        self.wifi_service = wifi_service
        self.auth_username = auth_username
        self.auth_password = auth_password
        self.port = port
        self.error_manager = ErrorManager()
        self.server_task = None
        self.is_running = False
        
    async def start(self):
        """Start the OTA update server"""
        if self.server_task is not None:
            self.error_manager.log_warning("OTA server already running")
            return
            
        self.is_running = True
        self.server_task = asyncio.create_task(self._server_loop())
        self.error_manager.log_info(f"OTA update server started on port {self.port}")
        
    async def stop(self):
        """Stop the OTA update server"""
        if self.server_task is None:
            return
            
        self.is_running = False
        self.server_task.cancel()
        try:
            await self.server_task
        except asyncio.CancelledError:
            pass
        self.server_task = None
        self.error_manager.log_info("OTA update server stopped")
    
    async def _server_loop(self):
        """Main server loop"""
        # Create socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # Try to bind and start listening
        try:
            s.bind(('0.0.0.0', self.port))
            s.listen(5)
            s.setblocking(False)
            self.error_manager.log_info(f"OTA server listening on port {self.port}")
        except Exception as e:
            self.error_manager.log_error(f"Failed to start OTA server: {e}")
            return
            
        # Server loop
        while self.is_running:
            # Check if WiFi is connected
            if not self.wifi_service.is_connected():
                await asyncio.sleep(1)
                continue
                
            try:
                # Try to accept a connection (non-blocking)
                try:
                    # Non-blocking socket accept wrapped in try/except
                    try:
                        client_sock, addr = s.accept()
                    except OSError:
                        # No connection available, just continue the loop
                        await asyncio.sleep(0.1)
                        continue
                        
                    # If we get here, we have a connection
                    client_sock.setblocking(False)
                    self.error_manager.log_info(f"OTA connection from {addr}")
                    
                    # Handle this client directly in a new task
                    client_task = asyncio.create_task(
                        self._handle_socket_client(client_sock, addr)
                    )
                
                except Exception as e:
                    self.error_manager.log_error(f"Error accepting connection: {e}")
                    await asyncio.sleep(1)  # Wait before trying again
                    continue
                    
            except asyncio.CancelledError:
                self.error_manager.log_info("OTA server task cancelled")
                break
            except Exception as e:
                self.error_manager.log_error(f"OTA server error: {e}")
                await asyncio.sleep(1)  # Avoid tight loop on persistent errors
                
        # Clean up
        s.close()
        self.error_manager.log_info("OTA server closed")
        
    async def _handle_socket_client(self, client_sock, addr):
        """Handle a client socket connection directly"""
        try:
            # Buffer for request processing
            request = b""
            headers_complete = False
            content_length = 0
            boundary = None
            
            # Read HTTP headers
            while not headers_complete and len(request) < 8192:  # Limit header size
                try:
                    chunk = client_sock.recv(1024)
                    if not chunk:
                        break
                        
                    request += chunk
                    
                    # Check if we've reached the end of headers
                    if b"\r\n\r\n" in request:
                        headers_complete = True
                        
                except OSError:
                    # Socket would block, wait a bit
                    await asyncio.sleep(0.01)
            
            # Parse the request
            if not headers_complete:
                # Headers too large or connection dropped
                self._send_error_response(client_sock, 400, "Bad Request")
                return
                
            # Split into request line and headers
            headers_data, body = request.split(b"\r\n\r\n", 1)
            header_lines = headers_data.split(b"\r\n")
            request_line = header_lines[0].decode()
            
            # Parse headers into a dictionary
            headers = {}
            for line in header_lines[1:]:
                if b":" in line:
                    key, value = line.split(b":", 1)
                    headers[key.strip().lower().decode()] = value.strip().decode()
                    
            # Check authorization
            if not self._check_auth(headers):
                self._send_response(client_sock, 401, "Unauthorized", {
                    "WWW-Authenticate": "Basic realm=\"OTA Update\""
                }, "<html><body><h1>401 Unauthorized</h1></body></html>")
                return
                
            # Parse method and path
            try:
                method, path, _ = request_line.split(" ", 2)
            except ValueError:
                self._send_error_response(client_sock, 400, "Bad Request")
                return
                
            # Handle the request based on method and path
            if method == "GET":
                if path == "/" or path == "/index.html":
                    self._handle_upload_page(client_sock)
                else:
                    self._send_error_response(client_sock, 404, "Not Found")
            elif method == "POST":
                if path == "/upload":
                    await self._handle_socket_upload(client_sock, headers, body)
                else:
                    self._send_error_response(client_sock, 404, "Not Found")
            else:
                self._send_error_response(client_sock, 405, "Method Not Allowed")
                
        except Exception as e:
            self.error_manager.log_error(f"Error handling client socket: {e}")
            try:
                self._send_error_response(client_sock, 500, "Internal Server Error")
            except Exception:
                pass
        finally:
            # Clean up
            try:
                client_sock.close()
            except Exception:
                pass
                
    def _check_auth(self, headers):
        """Check the Authorization header for Basic auth"""
        if 'authorization' not in headers:
            return False
            
        auth_header = headers['authorization']
        if not auth_header.startswith('Basic '):
            return False
            
        try:
            # Decode the base64 auth string
            auth_decoded = ubinascii.a2b_base64(auth_header[6:].encode()).decode()
            username, password = auth_decoded.split(':', 1)
            return username == self.auth_username and password == self.auth_password
        except Exception:
            return False
                
    def _send_error_response(self, sock, status_code, status_message):
        """Send an error response to the socket"""
        message = f"<html><body><h1>{status_code} {status_message}</h1></body></html>"
        self._send_response(sock, status_code, status_message, 
                          {"Content-Type": "text/html"}, message)
    
    def _send_response(self, sock, status_code, status_message, headers, body):
        """Send a full HTTP response to the socket"""
        response = f"HTTP/1.1 {status_code} {status_message}\r\n"
        
        # Add headers
        for name, value in headers.items():
            response += f"{name}: {value}\r\n"
            
        # Add content length
        body_bytes = body.encode() if isinstance(body, str) else body
        response += f"Content-Length: {len(body_bytes)}\r\n"
        
        # End headers
        response += "\r\n"
        
        # Send headers
        sock.send(response.encode())
        
        # Send body
        sock.send(body_bytes)
        
    def _handle_upload_page(self, sock):
        """Send the upload HTML page to the socket"""
        self._send_response(sock, 200, "OK", {"Content-Type": "text/html"}, self._get_upload_html())
        
    def _get_upload_html(self):
        """Return the HTML for the upload page"""
        return """<!DOCTYPE html>
<html>
<head>
    <title>OTA Update - Opentherm Controller</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
        h1 { color: #333; }
        .form-group { margin-bottom: 15px; }
        label { display: block; margin-bottom: 5px; }
        .file-input { margin-bottom: 10px; }
        button { background-color: #4CAF50; color: white; padding: 10px 15px; border: none; cursor: pointer; }
        button:hover { background-color: #45a049; }
        #files-container { margin-bottom: 15px; }
        .progress { margin-top: 20px; }
        .progress-bar { height: 20px; background-color: #f1f1f1; border-radius: 5px; margin-top: 5px; }
        .progress-bar-inner { height: 100%; width: 0; background-color: #4CAF50; border-radius: 5px; transition: width 0.3s; }
    </style>
</head>
<body>
    <h1>OTA Firmware Update</h1>
    <div class="form-group">
        <label for="file-upload">Select firmware files to upload:</label>
        <div id="files-container">
            <input type="file" class="file-input" multiple>
        </div>
        <button id="add-file">Add More Files</button>
    </div>
    <button id="upload-btn">Upload Firmware</button>
    <div class="progress">
        <p id="status">Ready to upload</p>
        <div class="progress-bar">
            <div class="progress-bar-inner" id="progress"></div>
        </div>
    </div>

    <script>
        document.getElementById('add-file').addEventListener('click', function() {
            var input = document.createElement('input');
            input.type = 'file';
            input.className = 'file-input';
            document.getElementById('files-container').appendChild(input);
        });

        document.getElementById('upload-btn').addEventListener('click', async function() {
            const fileInputs = document.querySelectorAll('.file-input');
            const status = document.getElementById('status');
            const progressBar = document.getElementById('progress');
            
            let filesSelected = false;
            for (const input of fileInputs) {
                if (input.files.length > 0) {
                    filesSelected = true;
                    break;
                }
            }
            
            if (!filesSelected) {
                status.textContent = 'Please select at least one file to upload';
                return;
            }
            
            status.textContent = 'Uploading...';
            
            for (const input of fileInputs) {
                if (input.files.length === 0) continue;
                
                const file = input.files[0];
                const formData = new FormData();
                formData.append('file', file);
                formData.append('filename', file.name);
                
                try {
                    status.textContent = `Uploading ${file.name}...`;
                    
                    const xhr = new XMLHttpRequest();
                    xhr.open('POST', '/upload', true);
                    
                    xhr.upload.onprogress = function(e) {
                        if (e.lengthComputable) {
                            const percentComplete = (e.loaded / e.total) * 100;
                            progressBar.style.width = percentComplete + '%';
                        }
                    };
                    
                    xhr.onload = function() {
                        if (xhr.status === 200) {
                            status.textContent = `${file.name} uploaded successfully`;
                        } else {
                            status.textContent = `Error uploading ${file.name}: ${xhr.statusText}`;
                        }
                    };
                    
                    xhr.onerror = function() {
                        status.textContent = `Network error during upload of ${file.name}`;
                    };
                    
                    xhr.send(formData);
                    
                    // Wait for the upload to complete
                    await new Promise(resolve => {
                        xhr.onloadend = resolve;
                    });
                    
                } catch (error) {
                    status.textContent = `Error: ${error.message}`;
                    break;
                }
            }
            
            status.textContent = 'All uploads complete';
        });
    </script>
</body>
</html>
"""
        
    async def _handle_socket_upload(self, sock, headers, initial_body):
        """Handle a file upload request from a socket"""
        try:
            # Check content type
            content_type = headers.get('content-type', '')
            if not content_type.startswith('multipart/form-data'):
                self._send_error_response(sock, 400, "Bad Request - Expected multipart/form-data")
                return
                
            # Extract boundary
            boundary = None
            for part in content_type.split(';'):
                part = part.strip()
                if part.startswith('boundary='):
                    boundary = part[9:]
                    if boundary.startswith('"') and boundary.endswith('"'):
                        boundary = boundary[1:-1]
                    break
            
            if not boundary:
                self._send_error_response(sock, 400, "Bad Request - Missing boundary")
                return
                
            boundary_bytes = f"--{boundary}".encode()
            
            # Process the file upload
            buffer = initial_body
            
            # Find the start of the first boundary
            boundary_pos = buffer.find(boundary_bytes)
            if boundary_pos == -1:
                # If the boundary isn't in the initial buffer, read more data
                while len(buffer) < 4096:  # Reasonable limit
                    try:
                        chunk = sock.recv(1024)
                        if not chunk:
                            break
                        buffer += chunk
                        boundary_pos = buffer.find(boundary_bytes)
                        if boundary_pos != -1:
                            break
                    except OSError:
                        # Socket would block
                        await asyncio.sleep(0.01)
                        
            # If we still can't find the boundary, it's a bad request
            if boundary_pos == -1:
                self._send_error_response(sock, 400, "Bad Request - Could not find boundary")
                return
                
            # Move past the boundary
            buffer = buffer[boundary_pos + len(boundary_bytes) + 2:]  # +2 for CRLF
            
            # Extract Content-Disposition line
            end_header_pos = buffer.find(b"\r\n\r\n")
            if end_header_pos == -1:
                # Read more data if needed
                while end_header_pos == -1 and len(buffer) < 8192:
                    try:
                        chunk = sock.recv(1024)
                        if not chunk:
                            break
                        buffer += chunk
                        end_header_pos = buffer.find(b"\r\n\r\n")
                    except OSError:
                        # Socket would block
                        await asyncio.sleep(0.01)
                        
            if end_header_pos == -1:
                self._send_error_response(sock, 400, "Bad Request - Incomplete headers")
                return
                
            # Extract headers for this part
            part_headers = buffer[:end_header_pos].split(b"\r\n")
            buffer = buffer[end_header_pos + 4:]  # +4 for double CRLF
            
            # Extract filename from Content-Disposition
            filename = None
            for header in part_headers:
                if header.lower().startswith(b"content-disposition:"):
                    header_value = header.decode()
                    for part in header_value.split(';'):
                        part = part.strip()
                        if part.startswith('filename='):
                            filename = part[9:]
                            if filename.startswith('"') and filename.endswith('"'):
                                filename = filename[1:-1]
                            break
                            
            if not filename:
                self._send_error_response(sock, 400, "Bad Request - Missing filename")
                return
                
            # Process the file data
            await self._save_socket_file(sock, filename, buffer, boundary_bytes)
            
            # Send success response
            self._send_response(sock, 200, "OK", 
                              {"Content-Type": "text/plain"},
                              f"File {filename} uploaded successfully")
                
        except Exception as e:
            self.error_manager.log_error(f"Error handling file upload: {e}")
            self._send_error_response(sock, 500, "Internal Server Error")
            
    async def _save_socket_file(self, sock, filename, initial_buffer, boundary_bytes):
        """Save file data from socket to filesystem"""
        try:
            self.error_manager.log_info(f"Receiving file: {filename}")
            
            # Start with any data we already have in the buffer
            buffer = initial_buffer
            end_boundary = b"\r\n" + boundary_bytes
            
            # Open file for writing
            with open(filename, 'wb') as f:
                while True:
                    # Check if end boundary is in current buffer
                    boundary_pos = buffer.find(end_boundary)
                    if boundary_pos != -1:
                        # Write data up to the boundary
                        f.write(buffer[:boundary_pos])
                        break
                        
                    # Write what we have, keeping the last boundary length bytes
                    # in case the boundary spans a read
                    safe_write_len = max(0, len(buffer) - len(end_boundary))
                    if safe_write_len > 0:
                        f.write(buffer[:safe_write_len])
                        buffer = buffer[safe_write_len:]
                    
                    # Try to read more data
                    try:
                        data = sock.recv(BUFFER_SIZE)
                        if not data:
                            break
                        buffer += data
                    except OSError:
                        # Socket would block, yield control
                        await asyncio.sleep(0.01)
            
            self.error_manager.log_info(f"File saved: {filename}")
            
        except Exception as e:
            self.error_manager.log_error(f"Error saving file: {e}")
            raise 