import uasyncio as asyncio
import utime as time
from manager_error import ErrorManager
from manager_wifi import WiFiManager
from micropython_ota import check_version, check_for_ota_update, ota_update, generate_auth

class OverTheAirService:
    """Service for Over-The-Air updates using micropython-ota library"""
    
    def __init__(self, wifi_service, host, project, filenames=None, 
                 check_interval=3600, use_version_prefix=True,
                 user=None, password=None, auto_update=False):
        """Initialize the OTA update service
        
        Args:
            wifi_service (WiFiManager): WiFi manager instance
            host (str): OTA server host URL (e.g., "http://example.com")
            project (str): Project name on the server
            filenames (list): List of files to update (None to just check for updates)
            check_interval (int): Interval in seconds to check for updates
            use_version_prefix (bool): Whether to use version prefix in filenames
            user (str): Basic auth username (optional)
            password (str): Basic auth password (optional)
            auto_update (bool): Whether to automatically apply updates
        """
        self.wifi_service = wifi_service
        self.host = host
        self.project = project
        self.filenames = filenames or []
        self.check_interval = check_interval
        self.use_version_prefix = use_version_prefix
        self.user = user
        self.password = password
        self.auto_update = auto_update
        
        self.error_manager = ErrorManager()
        self.last_check_time = 0
        self.update_available = False
        self.remote_version = ""
        self.current_version = ""
        self.auth = generate_auth(user, password)
        self.running = False
        self.task = None
        
    async def start(self):
        """Start the OTA update service"""
        if self.task is not None:
            self.error_manager.log_warning("OTA service already running")
            return
            
        self.running = True
        self.task = asyncio.create_task(self._update_loop())
        self.error_manager.log_info(f"OTA update service started for project {self.project}")
        
    async def stop(self):
        """Stop the OTA update service"""
        if self.task is None:
            return
            
        self.running = False
        self.task.cancel()
        try:
            await self.task
        except asyncio.CancelledError:
            pass
        self.task = None
        self.error_manager.log_info("OTA update service stopped")

    async def _update_loop(self):
        """Main update loop - checks for updates periodically"""
        while self.running:
            try:
                if self.wifi_service.is_connected():
                    current_time = time.time()
                    # Check if it's time to check for updates
                    if (current_time - self.last_check_time) >= self.check_interval:
                        self.last_check_time = current_time
                        await self.check_for_update()
            except Exception as e:
                self.error_manager.log_error(f"Error in OTA update loop: {e}")
            
            # Wait before next iteration
            await asyncio.sleep(60)  # Check every minute if it's time for an update check

    async def check_for_update(self):
        """Check for an available update"""
        if not self.wifi_service.is_connected():
            self.error_manager.log_warning("Cannot check for updates: WiFi not connected")
            return False
            
        try:
            self.error_manager.log_info(f"Checking for updates from {self.host}/{self.project}")
            # Run the version check in a separate thread to not block the event loop
            # since check_version makes blocking HTTP requests
            version_changed, remote_version = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: check_version(self.host, self.project, auth=self.auth)
            )
            
            self.update_available = version_changed
            self.remote_version = remote_version
            
            # Get current version
            try:
                with open('version', 'r') as current_version_file:
                    self.current_version = current_version_file.readline().strip()
            except:
                self.current_version = "unknown"
                
            if version_changed:
                self.error_manager.log_info(f"Update available: version {remote_version}")
                if self.auto_update and self.filenames:
                    await self.apply_update()
            else:
                self.error_manager.log_info(f"No updates available (current: {self.current_version})")
                
            return version_changed
        except Exception as e:
            self.error_manager.log_error(f"Error checking for updates: {e}")
            return False

    async def apply_update(self):
        """Apply the available update"""
        if not self.update_available or not self.filenames:
            self.error_manager.log_warning("No update available or no files specified")
            return False
            
        if not self.wifi_service.is_connected():
            self.error_manager.log_warning("Cannot apply update: WiFi not connected")
            return False
            
        try:
            self.error_manager.log_info(f"Applying update to version {self.remote_version}")
            self.error_manager.log_info(f"Files to update: {', '.join(self.filenames)}")
            
            # Run the update in a separate thread to not block the event loop
            # since ota_update makes blocking HTTP requests and file operations
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: ota_update(
                    self.host, 
                    self.project, 
                    self.filenames,
                    use_version_prefix=self.use_version_prefix,
                    user=self.user,
                    passwd=self.password,
                    hard_reset_device=True,
                    soft_reset_device=False
                )
            )
            
            # If we get here, the update failed or didn't reset the device
            self.error_manager.log_warning("Update did not trigger device reset")
            return False
        except Exception as e:
            self.error_manager.log_error(f"Error applying update: {e}")
            return False
    
    def get_current_version(self):
        """Get the current firmware version"""
        return self.current_version
    
    def get_remote_version(self):
        """Get the latest remote version if available"""
        return self.remote_version if self.update_available else None
    
    def is_update_available(self):
        """Check if an update is available"""
        return self.update_available 