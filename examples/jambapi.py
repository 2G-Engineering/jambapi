""" JAMBAPI (Just Another ModBus API) 

	Prerequisites:
	- Python 3.x
	- minimalmodbus library
	- pyserial library

	Installation:
	- pip install pyserial
	- pip install minimalmodbus

    Example of library usage:
        poll_count = 0
        def actuator_poll_complete():
            global poll_count
            global actuator_jambui
            
            poll_count += 1
            print(f"Register: {actuator_jambui['COUNT'].name}, Value: {actuator_jambui['COUNT'].value}")
            
            if (actuator_jambui['COUNT'].value >= 10):
                actuator_jambui["COUNT"] = 0 # Reset the count
                
            if (poll_count > 20): #stop program after 20 loops
                actuator_jambui.stop_polling()

        actuator_jambui = JAMBAPI(port="COM31", baud=19200, map_path=None, timeout=1.0, slaveID=1, useUUIDCachedMap=True)

        if actuator_jambui:
            for reg in actuator_jambui:
                reg.set_query(False)
            actuator_jambui["COUNT"].set_query(True)  # Only poll this register
            actuator_jambui.start_polling(callback=actuator_poll_complete, interval=0.1)

    Notes:
        - map_path is the local or full path of the .csv map file.
        - useUUIDCachedMap will auto load previous saved maps

    Features:
        COMPLETE - Can be imported and run with no UI libraries (QT, etc) present.
        COMPLETE - Can connect to serial devices.
        COMPLETE - Connection parameters (baud rate, port number, etc.) can be specified.
        COMPLETE - Register map can either be downloaded from the device or specified as a file.
        COMPLETE - Once the register map has been imported, registers can be accessed by name or number.
        COMPLETE - Multi-part registers are parsed out into their constituent elements, with scaling applied as specified in the map
        COMPLETE - Registers are polled automatically, with a call back function to indicate when a polling cycle has completed.
        COMPLETE - Registers can be selected to be polled or not polled to reduce polling cycle times.
        - Multiple instances can be created. Each instance will have an independent polling loop which runs in parallel with any others that may be active
        - Multiple addresses can be specified when creating an instance to poll multiple devices on the same bus.
        COMPLETE - Cache map to ModbusRegistermaps subfolder
"""

# ######################################################################################################### #

import minimalmodbus as mmmb
import os, serial, time
from datetime import datetime
import re
import threading
import struct

# ######################################################################################################### #

_re_uuid  = re.compile(r"^# *?uuid *?: *?([0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})$")
_re_title = re.compile(r"^# *?title *?: *modbus register map for ([ -~]*)$")
REGISTERMAPADDRESS  = 130
REGISTERMAPNUMWORDS = 120

_re_digits = re.compile(r'\d')
def contains_digits(d):
    return bool(_re_digits.search(d))

def containsAny(seq, aset):
    """ Check whether sequence seq contains Any items in aset. """
    for c in seq:
        if c in aset:
            return True
    return False

class ModbusRegister:
    def __init__(self, register_info):
        self.register  = register_info['register']
        self.words_out = register_info['words_out']
        self.words_in  = register_info['words_in']
        self.persist   = register_info['persist']
        self.name      = register_info['name']
        self.packing   = register_info['packing']
        self.unit      = register_info['unit']
        self.formatStr = register_info['formatStr']
        self.hint      = register_info['hint']
        self.value     = None
        self.scalar    = None
        self.query     = True
        self.write_queued  = False
        self.raw_registers = None
        self.raw_hex       = None
        self.ptype     = "str"
        self.scale     = register_info["scale"]
        self.offset    = register_info["offset"]

        try: # check for list
            self.isList = len(struct.unpack(self.packing,bytearray(self.words_out*2))) > 1
        except Exception as e:
            if not containsAny(self.packing,"#"):
                print(f"error in packing string {self.packing} on {self.words_out*2} bytes. {e}")
            self.isList = False

        if contains_digits(self.packing):
            self.isList = True

        if self.isList:
            self.ptype = "str"
        else:
            if containsAny(self.packing,"fd"): # float32 or float64
                self.ptype = "float"

            if containsAny(self.packing,"BHLQbhlq"): # signed or unsigned integer items
                self.ptype = "int"

            if "s" in self.packing:
                self.ptype = "str"

            if self.scale:
                self.ptype = "float"

            # remove all known chars from the string and complain if anything remains
            leftovers = re.sub("[0123456789<>@=!#]", "", self.packing) # strip these
            if len(leftovers) > 1:
                # multiple types.. its a conglomerate list
                self.ptype = "str"

    def set_query(self, query):
        self.query = query

    def toggle_query(self):
        self.query = not self.query

    def __str__(self):
        #TBD: calculate the scaled value
        return str(self.scalar)  # Return scalar as a string

class JAMBAPI:
    def __init__(self, port, baud, map_path=None, timeout=1.0, slaveID=1, useUUIDCachedMap=False):
        self.port = port
        self.baud = baud
        self.map_file = map_path
        #self.timeout = timeout
        self.instrument = mmmb.Instrument(port, slaveID)
        self.instrument.serial.baudrate = baud
        self.instrument.serial.timeout = timeout
        self.useUUIDCachedMap = useUUIDCachedMap #checks folder for a cached map, and uses instead of reloading map.
        self.name_string = None
        self.uuid_string = None
        self.maplist = None
        self.num_registers = None
        
        #TBD
        self.registers = {}
        self.polling = False
        self.polling_thread = None
        self.callback = None
        
        self._initialize_device()
        self._create_register_dict()

    # ######################################################### #
    # MAP READER (INITIAL CONNECTION)
    # ######################################################### #

    def _initialize_device(self):
        # Load register map

        # parse map
        if self.map_file is None:
            self.num_registers = self._read_regmap_from_device()
        else:
            self.num_registers = self._read_regmap_from_file(self.map_file)

        # report after parsing map
        if self.num_registers and self.name_string:
            if self.map_file is None:
                print(f"{self.num_registers} registers were parsed from {self.name_string}")
                self.map_file = self._write_cached_regmap_to_file()
            else:
                print(f"{self.num_registers} registers were parsed from {self.map_file}")
        elif self.num_registers:
            print(f"{self.num_registers} registers were parsed.")
        else:
            print("Failed to read register map")
            return False
        return True

    def _read_regmap_from_device(self):
        print(f"Reading register map, please wait.")
        alldata=[]
        
        # reposition to start of header
        self.instrument.write_string(REGISTERMAPADDRESS, "-1", REGISTERMAPNUMWORDS)
        
        # read the open device and repeatedly query for subsequent lines of the register map
        while True:
            line = self.instrument.read_string(REGISTERMAPADDRESS, REGISTERMAPNUMWORDS).split("\0")
            if not line[0]:
                break
            for data in line:
                if not data:
                    break
                if self._extract_legend_data(data) and self.useUUIDCachedMap:
                    filename = f"{self.uuid_string}.csv"
                    full_path = os.path.join("ModbusRegistermaps", filename)
                    if os.path.exists(full_path):
                        print(f"Found cached register map: {filename}")
                        # Stop reading map, and use the cached version
                        if(self._read_regmap_from_file(filename)):
                            self.map_file = filename
                            return len(self.maplist) #exit only on good read
                    else:
                        print(f"Did not find cached register map: {filename}, continuing to read new register map.")
                alldata.append(data)
        self.maplist = alldata
        #print(self.maplist)
        return len(self.maplist)
        
    def _extract_legend_data(self, data):
        if not data or data[0] != "#":
            return False # not a header, exit

        if self.name_string is None:
            self.name_string = self._extract_title(data)
            if self.name_string:
                print(f"Found device name: {self.name_string}")
                return False

        if self.uuid_string is None:
            self.uuid_string = self._extract_uuid(data)
            if self.uuid_string:
                print(f"Found device uuid: {self.uuid_string}")
                return True

        return False

    def _extract_uuid(self, line):
        uuid = _re_uuid.search(line)
        if uuid is not None:
            uuid = uuid[1]
            if uuid == "00000000-0000-0000-0000-000000000000":
                uuid = None
        return uuid

    def _extract_title(self, line):
        title = _re_title.search(line)
        if title is not None:
            title = title[1]
        return title

    def _read_regmap_from_file(self, file_path):
        full_path = os.path.join("ModbusRegistermaps", file_path)
        
        # Check if the file exists
        if not os.path.exists(full_path):
            print(f"File not found: {full_path}")
            return False

        print(f"Reading register map from file: {full_path}")
        try:
            with open(full_path, 'r') as file:
                self.maplist = file.readlines()
                #print(self.maplist)  # TBD
            return True
        except IOError as e:
            print(f"Error reading file: {e}")
            return False

    def _write_cached_regmap_to_file(self):
        os.makedirs("ModbusRegistermaps", exist_ok=True) # Create the subfolder if it doesn't exist
        if self.uuid_string:
            filename = f"{self.uuid_string}.csv"
        else:
            filename = "registermap.csv"
        full_path = os.path.join("ModbusRegistermaps", filename)
            
        with open(full_path,"w") as f:
            f.write(f"# MiniMB {datetime.now().strftime(' updated register map %Y-%m-%d %H:%M:%S')}\n")
            try:
                f.write("\n".join(self.maplist))
            except Exception as e:
                print(f"Error writing to file: {e}")
                return False
        print(f"wrote register map to {os.path.basename(full_path)}")
        return full_path
        
    def _create_register_dict(self):
        self.registers = {}

        for line in self.maplist:
            # Skip lines that are not register definitions
            if not line.strip() or line.startswith('#') or ',' not in line:
                continue

            # Split the line into parts
            parts = line.split(',')
            if len(parts) < 9:  # Ensure there are enough elements
                continue

            # Extract the individual elements
            try:
                register  = int(parts[0].strip())
                words_out = int(parts[1].strip())
                words_in  = int(parts[2].strip())
                persist   = int(parts[3].strip())
                name      = self._clean_string(parts[4])
                packing   = self._clean_string(parts[5])
                unit      = self._clean_string(parts[6])
                formatStr = self._clean_string(parts[7])
                hint      = self._clean_string( parts[8])
                
            except ValueError:
                # Handle cases where conversion to int fails
                continue

            scale  = None
            offset = None

            if "," in packing:
                parts = packing.split(",")     # ">f,*.001,+200"
                packing  = parts[0]
                if len(parts) > 1: # can be /1000 or *.001
                    expr = parts[1]
                    if   expr[0] == "*": scale =     float(expr[1:])
                   #elif expr[0] == "/": scale = 1.0/float(expr[1:])
                    else               : scale =     float(expr)
                if len(parts) > 2:
                    offset = float(parts[2])  # can be signed or unsigned number
                # any other , separated items are ignored

            register_info = {
                "register" : register,
                "words_out": words_out,
                "words_in" : words_in,
                "persist"  : persist,
                "name"     : name,
                "packing"  : packing,
                "unit"     : unit,
                "formatStr": formatStr,
                "hint"     : hint,
                "scale"    : scale,
                "offset"   : offset,
            }

            self.registers[name] = ModbusRegister(register_info)

        #print(self.registers)

    def _clean_string(self, string):
        """
        Remove quotes from a string and handle blank strings.
        """
        string = string.strip().strip('"')
        return "" if string == "" else string

    # ######################################################### #
    # POLLING
    # ######################################################### #

    def start_polling(self, callback, interval):
        # Start polling registers at specified interval
        self.callback = callback
        self.polling = True
        self.polling_thread = threading.Thread(target=self._polling_loop, args=(interval,))
        self.polling_thread.start()

    def _polling_loop(self, interval):
        # The loop that polls the registers
        while self.polling:
            for name, register in self.registers.items():
                #try:
                    if '#' in register.packing:
                        continue
                    if register.write_queued:
                        #print(f"Writing '{register.value}' to register: '{name}'")
                        register.write_queued = False  # Reset flag for both pass or fail
                        # Pack the data according to the format string
                        packed_data = struct.pack(register.packing, register.value)
                        # Write the packed data to the register (words_in is from device's perspective)
                        self.instrument.write_register(register.register, register.value, register.words_in)
                        #TBD, delay before read back?
                    if register.query:
                        # Perform read operation of raw data (words_out is from device's perspective)
                        register.raw_registers = self.instrument.read_registers(register.register, register.words_out)
                            
                        # Convert list of registers to a properly formatted byte string
                        byte_response = b''.join(struct.pack('>H', val) for val in register.raw_registers)
                        register.raw_hex = byte_response.hex()

                        # Unpack the byte string according to the specified format
                        decoded_response = struct.unpack(register.packing, byte_response)[0]
                        register.value = decoded_response
                        #print(f"Register: '{name}' Raw Data: '{register.raw_registers}' Format: '{register.packing}' Raw (hex): '{register.raw_hex}' Decoded (Decimal): '{register.value}' Format: '{register.formatStr}'")
                        
                #except Exception as e:
                #    # Handle communication errors or log them as needed
                #    print(f"Error communicating with register '{name}': {e}")

            if self.callback:
                self.callback()
            time.sleep(interval)

    def stop_polling(self):
        # Stop the polling loop
        self.polling = False
        if self.polling_thread is not None:
            # Check if the current thread is not the polling thread before joining
            if self.polling_thread != threading.current_thread():
                self.polling_thread.join()
            self.polling_thread = None
           
    # ######################################################### #
    # REGISTER FORMATTING
    # ######################################################### #
 
    def portray(self,reg):
        type_to_bytes = {'B': 1, 'b': 1, 'H': 2, 'h': 2, 'L': 4, 'l': 4, 'Q': 8, 'q': 8}
        #print(f"Register: '{reg.name}' Raw Data (Hex): '{reg.raw_hex}' Format: '{reg.packing}' Format: '{reg.formatStr}' List: '{reg.isList}'")
        if reg.raw_hex is None:
            return "None"

        if reg.formatStr: #and display_opt_strFormat:
                                    
            if reg.isList:
                byte_size = type_to_bytes[reg.packing[-1]]
                chunk_size = byte_size * 2
                value = [int(reg.raw_hex[i:i+chunk_size], 16) for i in range(0, len(reg.raw_hex), chunk_size)]
            else:
                if reg.packing[-1] in ['d', 'f']:  # Check for double-precision float
                    byte_data = bytes.fromhex(reg.raw_hex)
                    value = struct.unpack(reg.packing, byte_data)[0]
                elif 'b' in reg.formatStr or 'x' in reg.formatStr:
                    value = int(reg.raw_hex, 16)
                else:
                    value = reg.raw_hex

            formatted_value = eval('f'+repr(reg.formatStr), {}, {"value": value})
            return formatted_value

        items = [ self.bytes_to_str(reg,item) for item in reg.raw_hex ]
        txt = ",".join(items)
        try:
            return str(txt)
        except Exception as e:
            #print(f"exception {e}\ntext was {reg.raw_hex}")
            return f"{reg.raw_hex}"
            
    def bytes_to_str(self, reg, val):

        text   = None
        suffix = f" {reg.unit}" #if display_opt_showUnits else ""

        if isinstance(val,bytes):
            #print(f"{reg.regname}, type is '{type(val)}', showQuoted={ag.display_opt_showQuoted}")
            if True: #display_opt_showQuoted:
                try:
                    text = val.strip(b"\x00").decode()
                except UnicodeDecodeError as e:
                    pass  # will be handled in the catchall below

        elif reg.ptype == 'float' or isinstance(val,float):
            decimals = -1 #display_opt_decimals  
            digits   = -1 #display_opt_digits
            if True: #display_opt_siPrefix:
                text   = fn.siFormat(val, precision=decimals if decimals != -1 else 3, suffix=reg.unit)
                suffix = ""
            else:
                if   digits <= 0 and decimals <= 0: fmt =  "{:f}"
                elif digits  > 0 and decimals  > 0: fmt = f"{{:{digits}.{decimals}f}}"
                elif digits  > 0                  : fmt = f"{{:{digits}f}}"
                else                              : fmt = f"{{:.{decimals}f}}"
                text = fmt.format(val)

        if text is None:
            text = str(val)

        return f"{text}{suffix}"

    # ######################################################### #
    # REGISTER ACCESS
    # ######################################################### #

    def __iter__(self):
        # Allow iteration over registers
        return iter(self.registers.values())

    def _find_register(self, key):
        if isinstance(key, int):
            # Search by register number
            for reg_info in self.registers.values():
                if reg_info.register == key:
                    return reg_info
        else:
            # Search by register name
            if key in self.registers:
                return self.registers[key]
        # If not found, raise KeyError
        raise KeyError(f"Register '{key}' not found")
        
    def __getitem__(self, key):
        return self._find_register(key)

    def __setitem__(self, key, value):
        register = self._find_register(key)
        if register is not None:
            register.write_queued = True
            register.value = value
        else:
            raise KeyError(f"Register '{key}' not found")

# ######################################################################################################### #
