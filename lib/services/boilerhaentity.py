import uasyncio as asyncio
import ujson
from umqtt.simple import MQTTClient
from initialization import logger


class BoilerController:
    def __init__(self, mqtt_broker, device_id="boiler", base_topic="mydevice/boiler",
             mqtt_user=None, mqtt_pass=None):
        
        self.device_id = device_id
        self.base_topic = base_topic
        self.mqtt_broker = mqtt_broker

        # Internal state
        self.mode = "off"
        self.target_temp = 50.0
        self.current_temp = 45.0
        self.away_mode = "OFF"
        self.manual_override = False

        self.client = MQTTClient(self.device_id, self.mqtt_broker, user=mqtt_user, password=mqtt_pass)
        self.client.set_callback(self._on_message)
        logger.info(f"BoilerController initialized with device_id: {self.device_id}, mqtt_broker: {self.mqtt_broker}, mqtt_user: {mqtt_user}, mqtt_pass: {mqtt_pass}")

    def _on_message(self, topic, msg):
        topic = topic.decode()
        msg = msg.decode()
        logger.info(f"Received message on topic: {topic}, message: {msg}")
        if topic == f"{self.base_topic}/mode/set":
            if msg in ["off", "eco", "heat"]:
                self.mode = msg

        elif topic == f"{self.base_topic}/target_temperature/set":
            try:
                self.target_temp = float(msg)
            except:
                pass

        elif topic == f"{self.base_topic}/away_mode/set":
            self.away_mode = "ON" if msg.upper() == "ON" else "OFF"

        elif topic == f"{self.base_topic}/override/set":
            self.manual_override = msg.upper() == "ON"
            self.client.publish(
                f"{self.base_topic}/override/state",
                b"ON" if self.manual_override else b"OFF",
                retain=True
            )

    def publish_discovery(self):
        # Water heater discovery
        logger.info(f"Publishing discovery for {self.device_id}")
        device_info = {
            "identifiers": [self.device_id],
            "name": "Boiler",
            "model": "Pico-Test BoilerSim",
            "manufacturer": "Nightshift"
            }
        boiler_discovery = {
            "name": "Boiler",
            "unique_id": f"{self.device_id}_001",
            "device": device_info,
            "mode_state_topic": f"{self.base_topic}/mode",
            "mode_command_topic": f"{self.base_topic}/mode/set",
            "modes": ["off", "eco", "heat"],
            "temperature_command_topic": f"{self.base_topic}/target_temperature/set",
            "temperature_state_topic": f"{self.base_topic}/target_temperature/state",
            "current_temperature_topic": f"{self.base_topic}/current_temperature",
            "away_mode_state_topic": f"{self.base_topic}/away_mode/state",
            "away_mode_command_topic": f"{self.base_topic}/away_mode/set",
            "temperature_unit": "C",
            "min_temp": 30,
            "max_temp": 70,
            "temp_step": 0.5,
            "availability_topic": f"{self.device_id}/status"
        }
        
        self.client.publish(
            f"homeassistant/water_heater/{self.device_id}/boiler/config",
            ujson.dumps(boiler_discovery),
            retain=True
        )
        logger.info(f"Published discovery for {self.device_id}")

        # Manual override switch discovery
        override_discovery = {
            "name": "Manual Override",
            "unique_id": f"{self.device_id}_manual_override",
            "device": device_info,
            "state_topic": f"{self.base_topic}/override/state",
            "command_topic": f"{self.base_topic}/override/set",
            "availability_topic": f"{self.device_id}/status"
        }
        logger.info(f"Publishing override discovery for {self.device_id}")
        self.client.publish(
            f"homeassistant/switch/{self.device_id}/boiler_manual_override/config",
            ujson.dumps(override_discovery),
            retain=True
        )
        logger.info(f"Published override discovery for {self.device_id}")
    def publish_state(self):
        self.client.publish(f"{self.device_id}/status", b"online", retain=True)
        self.client.publish(f"{self.base_topic}/mode", self.mode.encode(), retain=True)
        self.client.publish(f"{self.base_topic}/target_temperature/state", str(self.target_temp), retain=True)
        self.client.publish(f"{self.base_topic}/current_temperature", str(self.current_temp), retain=True)
        self.client.publish(f"{self.base_topic}/away_mode/state", self.away_mode.encode(), retain=True)
        self.client.publish(
            f"{self.base_topic}/override/state",
            b"ON" if self.manual_override else b"OFF",
            retain=True
        )
        logger.info(f"Published state for {self.device_id}")

    async def start(self):
        try:
            logger.info(f"Starting MQTT connection for {self.device_id}")
            self.client.connect()
            logger.info(f"Connected to MQTT for {self.device_id}")
            self.client.subscribe(f"{self.base_topic}/mode/set")
            logger.info(f"Subscribed to {self.base_topic}/mode/set for {self.device_id}")
            self.client.subscribe(f"{self.base_topic}/target_temperature/set")
            logger.info(f"Subscribed to {self.base_topic}/target_temperature/set for {self.device_id}")
            self.client.subscribe(f"{self.base_topic}/away_mode/set")
            logger.info(f"Subscribed to {self.base_topic}/away_mode/set for {self.device_id}")
            self.client.subscribe(f"{self.base_topic}/override/set")
            logger.info(f"Subscribed to {self.base_topic}/override/set for {self.device_id}")
        except Exception as e:
            logger.error(f"MQTT startup error: {e}")
            return  # or retry logic
        self.publish_discovery()
        self.publish_state()

        while True:
            self.client.check_msg()
            logger.info(f"Checked message for {self.device_id}")
            if not self.manual_override:
                if self.mode in ["eco", "heat"] and self.current_temp < self.target_temp:
                    self.current_temp += 0.2
                    logger.info(f"Increased current temperature for {self.device_id}")
                elif self.current_temp > self.target_temp:
                    self.current_temp -= 0.1    
                    logger.info(f"Decreased current temperature for {self.device_id}")
                self.current_temp = round(max(30, min(self.current_temp, 70)), 1)
                logger.info(f"Current temperature for {self.device_id} is {self.current_temp}")
            self.publish_state()
            logger.info(f"Published state for {self.device_id}")
            await asyncio.sleep(10)
