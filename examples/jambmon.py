""" JAMBMON (Just Another ModBus Monitor) 

	Prerequisites:
    - Python 3.x
    - minimalmodbus library
    - pyserial library

	Installation:
    - pip install pyserial minimalmodbus windows-curses numerize

"""
# ######################################################################################################### #

import jambapi
import threading
import curses
from numerize import numerize

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

actuator_jambui = jambapi.JAMBAPI(port=DEVICE_PORT, baud=DEVICE_BAUD, map_path=None, timeout=1.0, slaveID=DEVICE_ID, useUUIDCachedMap=True)

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

    if poll_count > 50:  # Stop program after 50 loops (TBD: delete me)
        actuator_jambui.stop_polling()
        curses.endwin()  # Should close the curses window, but it doesn't

def generate_register_list(sort_type='numerical', display_all=False):
    # When query enabled or display all, add register to list
    filtered_registers = [reg for reg in actuator_jambui if reg.query or display_all]

    # Sorting based on sort_type
    if sort_type == 'alphabetical':
        sorted_registers = sorted(filtered_registers, key=lambda reg: reg.name.lower())
    else:  # Default to numerical sorting
        sorted_registers = sorted(filtered_registers, key=lambda reg: reg.register)

    # Extracting the names from the sorted register objects
    return [reg.name for reg in sorted_registers]

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

def draw_table(stdscr, sorted_registers, selected_row, display_all):
    # Define column widths
    column_widths = [8, 6, 22, 43, 40]
    start_row = 0
    start_col = 0

    # Get window dimensions
    max_row, max_col = stdscr.getmaxyx()

    # Draw headers within window size limits
    headers = ["Address", "Query", "Name", "Value", "Hint"]
    for i, header in enumerate(headers):
        if start_col + sum(column_widths[:i + 1]) < max_col:
            stdscr.addstr(start_row, start_col + sum(column_widths[:i]), header.ljust(column_widths[i]))

    # Draw data rows within window size limits
    row = start_row + 1
    row_index = 0
    for reg_name in sorted_registers:
        reg = actuator_jambui[reg_name]  # Access the register object
        if (display_all or reg.query) and row < max_row - 1:  # Leave space for footer
            if not is_number(reg.value):
                if is_byte_string(reg.value):
                    formatted_value = reg.value.decode('utf-8').rstrip('\x00') + reg.unit
                else:
                    formatted_value = str(reg.value) + reg.unit
            elif reg.formatStr == "":
                formatted_value = sci_notation_formatter(reg.value) + reg.unit
            else:
                formatted_value = actuator_jambui.portray(reg) #apply the format string
                
            # Highlight the selected row (reverse video mode)
            if row_index == selected_row:
                stdscr.attron(curses.A_REVERSE)

            # Dynamically truncate and display each column
            col_pos = start_col
            for i, data in enumerate([str(reg.register), str(reg.query), reg.name, formatted_value, reg.hint]):
                if col_pos + column_widths[i] < max_col:
                    stdscr.addstr(row, col_pos, data.ljust(column_widths[i])[:column_widths[i]])
                col_pos += column_widths[i]

            if row_index == selected_row:
                stdscr.attroff(curses.A_REVERSE)

            row += 1
            row_index += 1

# ######################################################################################################### #

WRITE_STRING = "Enter new value: "

def draw_footer(stdscr, start_row, start_col, display_all, write_mode = False):
    if write_mode:
        footer_string = WRITE_STRING
    else:
        if display_all:
            footer_string = "q = Quit | d = Display All Toggle | P = Poll Register | C = Device Polling | S = Change Sort | enter = Write"
        else:  # filtered view
            footer_string = "q = Quit | d = Display All Toggle | C = Device Polling | S = Change Sort  |  enter = Write"

    #Display the footer
    stdscr.addstr(start_row, start_col, footer_string)

def main(stdscr):
    selected_row = 0
    display_all = False
    write_mode = False
    ENTER_KEY = 10
    new_value = ""
    start_communication = True
    sort_type = "numerical"
    
    # Initialize curses
    curses.curs_set(0)  # Hide the cursor
    stdscr.nodelay(True)  # Make getch() non-blocking
    stdscr.clear()  # Clear the screen

    while True:
        filter_sorted_register_list = generate_register_list(sort_type=sort_type, display_all=display_all)

        stdscr.clear()  # Clear the screen for fresh drawing
        height, width = stdscr.getmaxyx()  # Get the size of the terminal window

        # Draw your table
        draw_table(stdscr, filter_sorted_register_list, selected_row, display_all)

        # Draw the footer with instructions
        draw_footer(stdscr, height - 1, 0, display_all, write_mode)  # Draw at the bottom of the screen

        # If in write mode, display the new value prompt and user input
        if write_mode:
            stdscr.addstr(height - 1, len(WRITE_STRING), new_value)
            stdscr.move(height - 1, len(WRITE_STRING) + len(new_value))
        else:
            draw_footer(stdscr, height - 1, 0, display_all)
        
        # Refresh the screen
        stdscr.refresh()

        # Wait for user input
        k = stdscr.getch()
        
        if k == ENTER_KEY:
            if not write_mode:
                write_mode = True
                new_value = ""
            else:
                write_mode = False
                try:
                    selected_reg_name = filter_sorted_register_list[selected_row]
                    actuator_jambui[selected_reg_name] = int(new_value) #TBD: works for numbers only for now
                except Exception as e:
                    print(f"Error writing to register {selected_reg_name}: {e}") #TBD: should print to footer for a while
        elif write_mode and k >= 32 and k <= 126:  # Accept printable characters
            new_value += chr(k)
        elif write_mode and k == 127:  # Handle backspace
            new_value = new_value[:-1]
                
        elif k == ord('q'):  # Quit if 'q' is pressed
            actuator_jambui.stop_polling()
            start_communication = False
            break #exit curses window
            
        elif k == ord('s'): # Toggle sorting  mode
            if sort_type == "numerical":    
                sort_type = "alphabetical"
            else:
                sort_type = "numerical"
                
        elif k == ord('d'): # Toggle display mode
            display_all = not display_all  
            
        elif k == ord('p'): # Toggle poll functionality for the selected register
            selected_reg_name = filter_sorted_register_list[selected_row]
            actuator_jambui[selected_reg_name].toggle_query()
            
        elif k == ord('c'):
            if start_communication:
                actuator_jambui.stop_polling()
                start_communication = False
            else:
                actuator_jambui.start_polling(callback=actuator_poll_complete, interval=0.1)
                start_communication = True
                
        elif k == curses.KEY_UP:
            selected_row = max(0, selected_row - 1)
        elif k == curses.KEY_DOWN:
            selected_row = min(selected_row + 1, len(filter_sorted_register_list) - 1)
            

# Run the polling in a separate thread
polling_thread = threading.Thread(target=polling_thread_function)
polling_thread.start()

# Run the curses application
curses.wrapper(main)