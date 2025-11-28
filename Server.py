import socket
import time
import csv
import struct
import collections
import os
from datetime import datetime

# Configuration
SERVER_PORT = 12000
HEADER_FORMAT = '!HHIB'  # device_id(2), seq_num(2), timestamp(4), msg_type(1)
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

# Use hardcoded project paths for logging (user requested)
BASE_DIR = r"D:\Courses\Network\Project"
OUTPUT_DIR = r"D:\Courses\Network\Project\Output"
os.makedirs(OUTPUT_DIR, exist_ok=True)
LOG_FILE = os.path.join(OUTPUT_DIR, 'telemetry_log.csv')

# The timeout for a heartbeat before we consider client disconnected
HEARTBEAT_TIMEOUT = 10000
# Message types
MSG_DATA = 0x01
MSG_HEARTBEAT = 0x02

# Create UDP socket
server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
server_socket.bind(('', SERVER_PORT))
print(f"Server listening on port {SERVER_PORT}...")

# Per-device state storage
device_state = {}  # {device_id: {'last_seq': num, 'last_time': time, 'received_seqs': set()}}

# Initialize CSV log file
with open(LOG_FILE, 'w', newline='') as csvfile:
    writer = csv.writer(csvfile)
    writer.writerow(['device_id', 'seq', 'timestamp', 'arrival_time', 'duplicate_flag', 'gap_flag'])


def parse_packet(data):
    """Parse binary packet and extract header fields"""
    if len(data) < HEADER_SIZE:
        return None

    device_id, seq_num, timestamp, msg_type = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
    payload = data[HEADER_SIZE:]

    return {
        'device_id': device_id,
        'seq_num': seq_num,
        'timestamp': timestamp,
        'msg_type': msg_type,
        'payload': payload
    }


def log_to_csv(device_id, seq_num, timestamp, arrival_time, is_duplicate, has_gap):
    """Log received packet to CSV file"""
    with open(LOG_FILE, 'a', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([device_id, seq_num, timestamp, arrival_time,
                         int(is_duplicate), int(has_gap)])


# Main receive loop
while True:
    try:
        # Receive packet
        data, address = server_socket.recvfrom(1024)
        arrival_time = time.time()

        # Parse packet
        packet = parse_packet(data)
        if packet is None:
            print(f"Invalid packet from {address}")
            continue

        device_id = packet['device_id']
        seq_num = packet['seq_num']
        timestamp = packet['timestamp']
        msg_type = packet['msg_type']

        # Initialize device state if first time seeing this device
        if device_id not in device_state:
            device_state[device_id] = {
                'last_seq': -1,
                'last_time': 0,
                'received_seqs': set()
            }

        state = device_state[device_id]

        # Check for duplicate
        is_duplicate = seq_num in state['received_seqs']

        # Check for gap (packet loss)
        has_gap = False
        if state['last_seq'] != -1 and seq_num > state['last_seq'] + 1:
            gap_size = seq_num - state['last_seq'] - 1
            has_gap = True
            print(
                f"[Device {device_id}] Detected packet loss: {gap_size} packet(s) missing (last: {state['last_seq']}, current: {seq_num})")

        # Handle duplicate
        if is_duplicate:
            print(f"[Device {device_id}] Duplicate packet detected: seq={seq_num}")
        else:
            # Update state for new packet
            state['received_seqs'].add(seq_num)
            if seq_num > state['last_seq']:
                state['last_seq'] = seq_num
            state['last_time'] = arrival_time

        # Log to CSV
        log_to_csv(device_id, seq_num, timestamp, arrival_time, is_duplicate, has_gap)

        # Print message info
        msg_type_str = "DATA" if msg_type == MSG_DATA else "HEARTBEAT" if msg_type == MSG_HEARTBEAT else "UNKNOWN"
        print(f"[Device {device_id}] Received {msg_type_str} - Seq: {seq_num}, From: {address}")

    except KeyboardInterrupt:
        print("\nServer shutting down...")
        break
    except Exception as e:
        print(f"Error: {e}")

server_socket.close()
