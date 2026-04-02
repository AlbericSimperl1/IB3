import serial
import time
import re
import math


## methodiek overgenomen uit scanner- en visainterface.cs
class XpertMillScanner:

##seriele communicatie met cnc controller
    def __init__(self, port="COM5", baudrate=115200):
        self.port = port
        self.baudrate = baudrate
        self.session = None
        
        self.last_x = 0
        self.last_y = 0
        self.last_z = 0
        
        self.reference_x = 0
        self.reference_y = 0
        self.reference_z = 0
        
        self.open = False
        
        # Regular expression used to extract the coordinates from the position string
        self.pos_regex = re.compile(r";PA=([0-9]+),([0-9]+),([0-9]+);")

## start seriele verbinding
    def open_device(self):
        self.session = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1
        )
        self.open = True

    def close_device(self):
        if self.session and self.session.is_open:
            self.session.close()
        self.open = False

    def initialise_device(self):
        if not self.open:
            self.open_device()
        # Send initialisation command
        self._write("!N;")
        # Reset the device
        self.reset_device()

    def reset_device(self):
        pos_string = self.get_exact_position()
        self._extract_xyz(pos_string)
        
        self.goto_position(self.last_x, self.last_y, 0)
        
        # reset commando
        self._write("RF1;RF2;RF3;")
        
        # reset positie
        self._set_last_position(0, 0, 0)
        self._set_reference_position(0, 0, 0)

    def goto_position(self, x, y, z):
        cmd = f"GA{x},{y},{z};"
        self._write(cmd)
        
        # wachttijd
        max_pos_delta = self._calculate_maximum_delta(x, y, z)
        delay_ms = self._calculate_delay(max_pos_delta)
        time.sleep(delay_ms / 1000.0)
        
        # save positie
        self._set_last_position(x, y, z)

    def get_exact_position(self):
        self._write("?PA;")
        time.sleep(0.025)
        
        if self.session and self.session.is_open:
            if self.session.in_waiting > 0:
                response = self.session.read(self.session.in_waiting).decode('ascii', errors='ignore')
                return response
        return ""

    def set_virtual_reference(self, x, y, z):
        cmd = f"SVN1,{x};SVN2,{y};SVN3,{z};"
        self._set_reference_position(x, y, z)
        self._write(cmd)

    def goto_virtual_reference(self):
        self._write("GA0,0,0;")
        
        max_pos_delta = self._calculate_maximum_delta(self.reference_x, self.reference_y, self.reference_z)
        delay_ms = self._calculate_delay(max_pos_delta)
        time.sleep(delay_ms / 1000.0)
        
        self._set_last_position(0, 0, 0)

    def set_last_position(self, x, y, z):
        self._set_last_position(x, y, z)

    # underscore → inwendig?

    def _write(self, text):
        if self.session and self.session.is_open:
            full_command = text + '\n'
            self.session.write(full_command.encode('ascii'))

    def _set_last_position(self, x, y, z):
        self.last_x = int(x)
        self.last_y = int(y)
        self.last_z = int(z)

    def _set_reference_position(self, x, y, z):
        self.reference_x = int(x)
        self.reference_y = int(y)
        self.reference_z = int(z)

    def _calculate_maximum_delta(self, x, y, z):
        dx = abs(x - self.last_x)
        dy = abs(y - self.last_y)
        dz = abs(z - self.last_z)
        return max(dx, dy, dz)

    def _calculate_delay(self, max_pos_delta):
        if max_pos_delta <= 5666:
            return 250
        else:
            return int(math.ceil((max_pos_delta / 34.0) * 1.5))

    def _extract_xyz(self, position_string):
        if not position_string:
            return
        match = self.pos_regex.search(position_string)
        if match:
            self.last_x = int(match.group(1))
            self.last_y = int(match.group(2))
            self.last_z = int(match.group(3))




if __name__ == "__main__":
    scanner = XpertMillScanner(port="COM5", baudrate=115200)
    try:
        scanner.initialise_device()
        scanner.goto_position(100, 100, 0)
        pos = scanner.get_exact_position()
        print(f"position: {pos}")
    except Exception as e:
        print(f"error: {e}")
    finally:
        scanner.close_device()
