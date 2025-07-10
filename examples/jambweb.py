""" JAMBMON (Just Another ModBus Website) 

	Prerequisites:
    - Python 3.x

	Installation:
    - pip install pyserial minimalmodbus numerize flask

"""
# ######################################################################################################### #

import jambapi
from flask import Flask, render_template, jsonify, request
import threading
from numerize import numerize
import webbrowser

# ######################################################################################################### #

DEVICE_PORT = "COM8"
DEVICE_ID = 1
DEVICE_BAUD = 115200

DEFAULT_FILTER = ["COUNT", "BUILD_NUM", "ERR", "RTC", "LAST", "BUILD_DATE", "VERSIONSTR", 
                  "MONITOR_PASS", "MONITOR_FAIL", "BAUD1", "BAUD2", "MODBUSADDR", "UNIQUEID", "DEVICE_NAME",
                  "SCREENSAVE", "UPTIME", "METER_DC_AC_MODE", "METER_VOLTAGE_RMS", "METER_CURRENT_RMS", 
                  "METER_LINE_FREQUENCY", "METER_POWER_FACTOR", "METER_ACTIVE_POWER", "METER_REACTIVE_POWER", 
                  "METER_APPARANT_POWER", "ENERGY_COMMAND",

"COUNT", "ERR", "FTP", "DATA", "REGMAP", "END1", "END2", "END4", 
"FLOAT32", "FLOAT64", 
"FACT", 
"MAP_VERSION", "VERS_MAJOR", "VERS_MINOR", "BUILD_NUM", "BUILD_DATE", "SERIAL_NUM", "BOARD_INFO_1", "BOARD_INFO_2", 
"UPTIME", "RTC", "MAC_ADDR", "RESERVED_1", "ISP_MODE", "SYS_RESET", "LOAD_DEFAULTS", "WRITE_CONFIG", "SYSTEM_FAULTS", 
"RESERVED_2", "SERIAL_BAUD", "SERIAL_TERM", "MODBUS_ADDR", "MODBUS_MODE", "MODBUS_ZERODELAY", "HOST_COM_TIMEOUT", 
"COM_TIMEOUT_ACTION", "IP_CONFIG", "IP4_GW", "IP4_MASK", "IP4_ADDR", "GNDF_SCAN_MODE", "GNDF_SCAN_LIST", 
"GNDF_AUTO_CAL", "XDCR_GAIN", "XDCR_OFFSET", "DISP_EN", "OUT1V_RAMP", "OUT1I_RAMP", "OUT1V_DEFAULT", "OUT1I_DEFAULT"

                  ]   

# ######################################################################################################### #

app = Flask(__name__)

json_data = {}
poll_count = 0
actuator_jambui = None
polling_thread = None
display_all = False
is_unfiltered = False

# ######################################################################################################### #

def create_app():
    global actuator_jambui, polling_thread
    
    app = Flask(__name__, template_folder='.')

    # Initialize JAMBAPI instance and start polling thread here
    actuator_jambui = jambapi.JAMBAPI(port=DEVICE_PORT, baud=DEVICE_BAUD, map_path=None, timeout=1.0, slaveID=DEVICE_ID, useUUIDCachedMap=True)
    polling_thread = threading.Thread(target=polling_thread_function)
    polling_thread.start()

    @app.route('/')
    def index():
        global display_all
        
        display_all = False #render with filter on
        update_json_data(filtered_register_list())
        
        return render_template('jambweb_template.html', data=json_data, display_all=display_all)

    @app.route('/update_data')
    def update_data():
        # Return the latest data as JSON for the JavaScript to use
        return json_data
        
    @app.route('/unfiltered')
    def unfiltered():
        global display_all
        
        display_all = True #re-render with filter off
        update_json_data(filtered_register_list())
        
        return render_template('jambweb_template.html', data=json_data, display_all=display_all)

    @app.route('/write_data', methods=['POST'])
    def write_data():
        register_name = request.form.get('register_name')
        value = request.form.get('value')
        print(f"Write Request: register_name: {register_name}, value = {value}")
        actuator_jambui[register_name] = int(value) #TBD: works for numbers only for now
        return jsonify({"success": True, "message": f"Data written to {register_name}: {value}"})

    return app

# ######################################################################################################### #

def polling_thread_function():
    global poll_count
    poll_count = 0

    # Set up the registers for polling based on the DEFAULT_FILTER
    if DEFAULT_FILTER:
        for reg in actuator_jambui:
            if reg.name in DEFAULT_FILTER:
                reg.set_query(True)
            else:
                reg.set_query(False)
            
    # Start polling
    actuator_jambui.start_polling(callback=actuator_poll_complete, interval=0.1)

def actuator_poll_complete():
    global poll_count
    poll_count += 1
    
    if poll_count == 1:
        webbrowser.open("http://127.0.0.1:5000/")

    #if poll_count > 10:  # Stop program after 10 loops (TBD: delete me)
    #    actuator_jambui.stop_polling()

    update_json_data(filtered_register_list())

def filtered_register_list():
    global display_all
    
    # When query enabled or display all, add register to list
    filtered_registers = [reg for reg in actuator_jambui if reg.query or display_all]

    # Extracting the names from the filtered register objects
    return [reg.name for reg in filtered_registers]

# ######################################################################################################### #

def sci_notation_formatter(value):
    if value is None or value == 0:
        return "0"
    
    abs_value = abs(value)
    if abs_value >= 1:
        numerized_value = numerize.numerize(value)
        if numerized_value is None:
            return str(value)  # Fallback to the default string representation
        return numerized_value
    else:
        return f"{value:.2e}"
        
def is_number(s):
    if s is None:
        return False
    try:
        float(s)  # for int, long, and float
    except ValueError:
        return False
    return True

def is_byte_string(s):
    return isinstance(s, bytes)

def update_json_data(sorted_registers, display_all=True):
    global json_data
    json_data = {}  # Reset json_data

    for reg_name in sorted_registers:
        reg = actuator_jambui[reg_name]  # Access the register object
        if (display_all or reg.query):  # Check if the register is set to be queried
            # Format the value based on its type
            if not is_number(reg.value):
                if is_byte_string(reg.value):
                    formatted_value = reg.value.decode('utf-8').rstrip('\x00') + reg.unit
                else:
                    formatted_value = str(reg.value) + " " + reg.unit
            elif reg.formatStr == "":
                formatted_value = str(reg.value) + " " + reg.unit #sci_notation_formatter(reg.value) + reg.unit
            else:
                formatted_value = actuator_jambui.portray(reg)  # Apply the format string

            # Store the data in a dictionary
            json_data[reg_name] = {
                'address': reg.register,
                'query': reg.query,
                'name': reg.name,
                'value': formatted_value,
                'hint': reg.hint
            }

# ######################################################################################################### #

if __name__ == '__main__':
    # Create the app and run it
    app = create_app()
    try:
        app.run(debug=False)
    except KeyboardInterrupt:
        print("Stopping Flask server...")
        actuator_jambui.stop_polling()