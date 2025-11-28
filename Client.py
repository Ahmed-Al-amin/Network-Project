import socket
import time
import struct
import random
from datetime import datetime

# Configuration
SERVER_HOST = 'localhost'
SERVER_PORT = 12000
DEVICE_ID = 1001  # Unique ID for this sensor
REPORTING_INTERVAL = 2  # seconds between reports
HEARTBEAT_INTERVAL = 5  # seconds between heartbeats when no data
HEADER_FORMAT = '!HHIB'  # device_id(2), seq_num(2), timestamp(4), msg_type(1)

# Message types
MSG_DATA = 0x01
MSG_HEARTBEAT = 0x02

# Create UDP socket
client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
print(f"Sensor {DEVICE_ID} starting...")

# Initialize sequence number
seq_num = 0


def create_data_packet(device_id, seq_num, sensor_readings):
    """Create a DATA packet with sensor readings"""
    timestamp = int(time.time())
    msg_type = MSG_DATA

    # Pack header
    header = struct.pack(HEADER_FORMAT, device_id, seq_num, timestamp, msg_type)

    # Pack payload (sensor readings)
    # Format: temperature(float), humidity(float), voltage(float)
    payload = struct.pack('!fff',
                          sensor_readings['temperature'],
                          sensor_readings['humidity'],
                          sensor_readings['voltage'])

    return header + payload


def create_heartbeat_packet(device_id, seq_num):
    """Create a HEARTBEAT packet (no payload)"""
    timestamp = int(time.time())
    msg_type = MSG_HEARTBEAT

    # Pack header only (no payload for heartbeat)
    packet = struct.pack(HEADER_FORMAT, device_id, seq_num, timestamp, msg_type)

    return packet


def generate_sensor_readings():
    """Simulate sensor readings"""
    return {
        'temperature': round(random.uniform(20.0, 30.0), 2),  # Celsius
        'humidity': round(random.uniform(30.0, 70.0), 2),  # Percentage
        'voltage': round(random.uniform(3.0, 5.0), 2)  # Volts
    }


# Main send loop
try:
    last_data_time = 0

    while True:
        current_time = time.time()

        # Decide whether to send DATA or HEARTBEAT
        # Simulate: 70% chance of having new data
        has_new_data = random.random() < 0.7

        if has_new_data and (current_time - last_data_time >= REPORTING_INTERVAL):
            # Generate sensor readings
            readings = generate_sensor_readings()

            # Create DATA packet
            packet = create_data_packet(DEVICE_ID, seq_num, readings)

            # Send packet (fire-and-forget, no response expected)
            client_socket.sendto(packet, (SERVER_HOST, SERVER_PORT))

            print(f"[{datetime.now().strftime('%H:%M:%S')}] Sent DATA #{seq_num} - "
                  f"Temp: {readings['temperature']}°C, "
                  f"Humidity: {readings['humidity']}%, "
                  f"Voltage: {readings['voltage']}V")

            last_data_time = current_time
            seq_num += 1

        elif current_time - last_data_time >= HEARTBEAT_INTERVAL:
            # Send HEARTBEAT if no data for a while
            packet = create_heartbeat_packet(DEVICE_ID, seq_num)

            client_socket.sendto(packet, (SERVER_HOST, SERVER_PORT))

            print(f"[{datetime.now().strftime('%H:%M:%S')}] Sent HEARTBEAT #{seq_num}")

            last_data_time = current_time
            seq_num += 1

        # Sleep briefly before next iteration
        time.sleep(1)

except KeyboardInterrupt:
    print(f"\n\nSensor {DEVICE_ID} shutting down...")
    print(f"Total packets sent: {seq_num}")
    client_socket.close()
except Exception as e:
    print(f"Error: {e}")
    client_socket.close()
