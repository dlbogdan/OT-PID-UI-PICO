import utime

# MCP23017 Port Expander
class Portexpander:
    IODIRA = 0x00
    IODIRB = 0x01
    GPIOA = 0x12
    GPIOB = 0x13
    OLATA = 0x14
    OLATB = 0x15
    GPPUA = 0x0C
    GPPUB = 0x0D

    def __init__(self, i2c, address=0x20):
        self.i2c = i2c
        self.address = address
        self._iodira = 0xFF
        self._iodirb = 0xFF
        self._olata = 0x00
        self._olatb = 0x00
        self._write_register(self.IODIRA, self._iodira)
        self._write_register(self.IODIRB, self._iodirb)

    def _write_register(self, reg, value):
        self.i2c.writeto_mem(self.address, reg, bytes([value]))

    def _read_register(self, reg):
        return self.i2c.readfrom_mem(self.address, reg, 1)[0]

    def set_pullup(self, pin, enable):
        if pin < 8:
            reg = self.GPPUA
            current = self._read_register(reg)
            if enable:
                current |= (1 << pin)
            else:
                current &= ~(1 << pin)
            self._write_register(reg, current)
        else:
            pin -= 8
            reg = self.GPPUB
            current = self._read_register(reg)
            if enable:
                current |= (1 << pin)
            else:
                current &= ~(1 << pin)
            self._write_register(reg, current)

    def set_pin_mode(self, pin, mode):
        if pin < 8:
            if mode == "output":
                self._iodira &= ~(1 << pin)
            else:
                self._iodira |= (1 << pin)
            self._write_register(self.IODIRA, self._iodira)
        else:
            pin -= 8
            if mode == "output":
                self._iodirb &= ~(1 << pin)
            else:
                self._iodirb |= (1 << pin)
            self._write_register(self.IODIRB, self._iodirb)

    def write_pin(self, pin, value):
        if pin < 8:
            if value:
                self._olata |= (1 << pin)
            else:
                self._olata &= ~(1 << pin)
            self._write_register(self.OLATA, self._olata)
        else:
            pin -= 8
            if value:
                self._olatb |= (1 << pin)
            else:
                self._olatb &= ~(1 << pin)
            self._write_register(self.OLATB, self._olatb)

    def read_pin(self, pin):
        if pin < 8:
            value = self._read_register(self.GPIOA)
            return (value & (1 << pin)) != 0
        else:
            pin -= 8
            value = self._read_register(self.GPIOB)
            return (value & (1 << pin)) != 0

# VirtualPin emulates machine.Pin interface for MCP23017 pins
class McpPin:
    IN = 0
    OUT = 1
    PULL_UP = 2  # MCP23017 only supports pull-up, not pull-down

    def __init__(self, expander, pin, mode=IN, pull=None):
        self.expander = expander
        self.pin = pin
        self.mode = mode
        self.pull = pull

        if mode == self.OUT:
            self.expander.set_pin_mode(pin, "output")
        else:
            self.expander.set_pin_mode(pin, "input")

        if pull == self.PULL_UP:
            self.expander.set_pullup(pin, True)

    def value(self, val=None):
        if val is None:
            return self.expander.read_pin(self.pin)
        else:
            if self.mode != self.OUT:
                raise RuntimeError("Cannot write to pin not set as output")
            self.expander.write_pin(self.pin, val)

    def on(self):
        self.value(1)

    def off(self):
        self.value(0)

# Alias for compatibility with machine.Pin-style code
Pin = McpPin
