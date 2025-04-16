# OTA Firmware Update Service for Pi Pico

This service provides Over-The-Air (OTA) firmware updates for MicroPython on the Raspberry Pi Pico via a simple HTTP web interface with basic authentication.

## Features

- Basic HTTP server for firmware updates
- Basic authentication for security
- Web interface for uploading firmware files
- Upload multiple files
- Progress indicators for uploads
- File replacement directly in flash storage

## Integration with Main Application

To integrate the OTA update service into your main application:

1. Import the OTA service:
```python
from service_ota import OTAUpdateService
```

2. Initialize the service with your existing WiFi service:
```python
ota_service = OTAUpdateService(
    wifi_service=wifi_service,  # Your existing WiFiManager instance
    auth_username="admin",      # Custom username or use default
    auth_password="otapico",    # Custom password or use default
    port=8080                   # Custom port or use default
)
```

3. Start the service in your main asyncio loop:
```python
await ota_service.start()
```

4. Add the service to your loop setup section in main.py:
```python
# In your main function where you set up tasks:
loop = asyncio.get_event_loop()
...
# Add the OTA service
ota_service = OTAUpdateService(wifi_service)
await ota_service.start()
...
loop.run_forever()
```

## Usage

Once the service is running:

1. Connect to the device using a web browser at: `http://<device-ip>:8080`
2. Enter the username and password when prompted
3. Use the web interface to upload firmware files
4. The files will be saved directly to the flash storage, replacing existing files with the same name

## Security Considerations

- The default credentials are: username `admin`, password `otapico`
- Change these default values in your application for security
- The service only starts when WiFi is connected
- Authentication is required for all operations

## Sample Standalone Usage

A sample script `ota_sample.py` is provided to demonstrate standalone usage:

```python
import uasyncio as asyncio
from manager_wifi import WiFiManager
from service_ota import OTAUpdateService

async def main():
    # Initialize WiFi
    wifi_service = WiFiManager("your_ssid", "your_password", "device-name")
    
    # Initialize OTA service
    ota_service = OTAUpdateService(wifi_service)
    
    # Start OTA service
    await ota_service.start()
    
    # Run your application
    while True:
        await asyncio.sleep(1)

asyncio.run(main())
```

## Limitations

- The service requires a connected WiFi network
- Large files may cause memory constraints on the Pico
- No verification of uploaded files is performed (future enhancement)
- No automatic reboot after update (must be manually triggered) 