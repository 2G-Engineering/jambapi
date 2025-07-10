"""
2G Modbus Register Map Reader

   Copyright 2023 D. Westaby

This script is designed to communicate with a Modbus device over a serial connection. It reads the 
register map of the device, extracts useful information such as the device name and UUID, and saves 
this data to a CSV file.

Prerequisites:
- Python 3.x
- minimalmodbus library
- pyserial library

Installation:
- pip install pyserial
- pip install minimalmodbus

Usage:
1. Update the `port`, `baudrate`, and `slaveID` variables in the script to match your Modbus device's configuration.
2. Run the script. It will attempt to connect to the device, read the register map, and save the data.
3. The script will print messages to the console about the progress and any issues encountered.
4. Once completed, the register map will be saved to the specified CSV file.
"""

import minimalmodbus as mmmb
import os, serial
from datetime import datetime
import re

###############################################################################
# Device Information
###############################################################################
port = "COM30"
baudrate = 115200
slaveID = 1

###############################################################################
# Application Globals
###############################################################################
name_string = None
uuid_string = None
maplist = None

REGISTERMAPADDRESS = 130
REGISTERMAPNUMWORDS = 120
TARGETCODEC = "latin1"

_re_uuid = re.compile(r"^# *?uuid *?: *?([0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})$")
def extract_uuid(line):
    uuid = _re_uuid.search(line)
    if uuid is not None:
        uuid = uuid[1]
        if uuid == "00000000-0000-0000-0000-000000000000":
            uuid = None
    return uuid

_re_title = re.compile(r"^# *?title *?: *modbus register map for ([ -~]*)$")
def extract_title(line):
    title = _re_title.search(line)
    if title is not None:
        title = title[1]
    return title

def _read_regmap_from_device():
    print(f"Reading register map, please wait.")
    global maplist
    alldata=[]
    
    # reposition to start of header
    instrument.write_string(REGISTERMAPADDRESS, "-1", REGISTERMAPNUMWORDS)
    
    # read the open device and repeatedly query for subsequent lines of the register map
    while True:
        line = instrument.read_string(REGISTERMAPADDRESS, REGISTERMAPNUMWORDS).split("\0")
        if not line[0]:
            break
        for data in line:
            if not data:
                break
            _extract_legend_data(data)
            alldata.append(data)
    maplist = alldata
    print(maplist)
    return len(maplist)

def _extract_legend_data(data):
    global name_string, uuid_string
    
    # parse some data in the register map header
    if not data or data[0] != "#":
        return False

    if name_string is None:
        name_string = extract_title(data)
        if name_string:
            print(f"Found device name: {name_string}")
            return True

    if uuid_string is None:
        uuid_string = extract_uuid(data)
        if uuid_string:
            print(f"Found device uuid: {uuid_string}")
            return True

    return True

def write_cached_regmap_to_file():
    global maplist, uuid_string
    if uuid_string:
        filename = f"{uuid_string}.csv"
    else:
        filename = "registermap.csv"
        
    with open(filename,"w") as f:
        f.write(f"# MiniMB {datetime.now().strftime(' updated register map %Y-%m-%d %H:%M:%S')}\n")
        try:
            f.write("\n".join(maplist))
        except Exception as e:
            print(f"Error writing to file: {e}")
            return False
    print(f"wrote register map to\n{os.path.basename(filename)}")
    return True

###############################################################################
# Example Usage:
###############################################################################

instrument = mmmb.Instrument(port, slaveID)
instrument.serial.baudrate = baudrate
num_registers = _read_regmap_from_device()

if num_registers and name_string:
    print(f"{num_registers} registers were parsed from {name_string}")
    write_cached_regmap_to_file()
elif num_registers:
    print(f"{num_registers} registers were parsed.")
else:
    print("Failed to read register map")
    