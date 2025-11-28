import socket
import time
import csv
import struct
import collections
from datetime import datetime


# Configuration
SERVER_PORT = 12000
HEADER_FORMAT = '!HHIB'  # device_id(2), seq_num(2), timestamp(4), msg_type(1)
HEADER_SIZE =  struct.calcsize(HEADER_FORMAT)
LOG_FILE = 'telemetry_log.csv'
Accepted_size = 200
total_packets = 0
batch_size = 5 #detected by team


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
device_state = {}  # {device_id: {'last_seq': num, 'last_time': time, 'received_seqs': set(), 'reorder_buffer': []}}


def reorder_by_timestamp(packets_buffer):
    """Sort packets buffer by timestamp for delayed packet reordering"""
    if not packets_buffer:
        return []
    return sorted(packets_buffer, key=lambda p: p['timestamp'])

# Initialize CSV log file
with open(LOG_FILE, 'w', newline='') as csvfile:
    writer = csv.writer(csvfile)
    writer.writerow(['device_id', 'seq', 'timestamp', 'arrival_time', 'duplicate_flag', 'gap_flag', 'checksum_valid'])


def compute_checksum(data: bytes) -> int:
    """Compute 16-bit checksum by summing all bytes and returning the lower 16 bits."""
    checksum = sum(data) & 0xFFFF
    return checksum


def parse_packet(data):
    """Parse binary packet and extract header fields"""
    if len(data) < HEADER_SIZE:
        return None

    # Extract header
    header = data[:HEADER_SIZE]
    device_id, seq_num, timestamp, msg_type = struct.unpack(HEADER_FORMAT, header)

    # Extract checksum (2 bytes after header)
    checksum_offset = HEADER_SIZE
    if len(data) < checksum_offset + 2:
        return None  # Not enough data for checksum

    received_checksum = struct.unpack('!H', data[checksum_offset:checksum_offset+2])[0]

    # Extract payload
    payload = data[checksum_offset + 2:]
    if len(payload) > Accepted_size:
        print("Payload too large")
        return None  # Exceeds max allowed size

    # Verify checksum
    computed_checksum = compute_checksum(header + payload)
    checksum_valid = (computed_checksum == received_checksum)

    return {
        'device_id': device_id,
        'seq_num': seq_num,
        'timestamp': timestamp,
        'msg_type': msg_type,
        'payload': payload,
        'checksum_valid': checksum_valid,
        'received_checksum': received_checksum,
        'computed_checksum': computed_checksum
    }


def log_to_csv(device_id, seq_num, timestamp, arrival_time, is_duplicate, has_gap, checksum_valid=True):
    """Log received packet to CSV file"""
    with open(LOG_FILE, 'a', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([device_id, seq_num, timestamp, arrival_time,
                         int(is_duplicate), int(has_gap), int(checksum_valid)])


# Metrics tracking
gap_packets = 0
duplicate_count = 0
sequence_gap_count = 0
total_processing_time = 0

# Main receive loop
while True:
    try:
        # Measure start time for CPU usage
        processing_start = time.perf_counter()

        # Receive packet
        data, address = server_socket.recvfrom(1024)
        total_packets += 1
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
        checksum_valid = packet.get('checksum_valid', True)

        # Check checksum validity
        if not checksum_valid:
            print(f"[Device {device_id}] Checksum mismatch: seq={seq_num} (expected: {packet['computed_checksum']}, got: {packet['received_checksum']})")

        # Initialize device state if first time seeing this device
        if device_id not in device_state:
            device_state[device_id] = {
                'last_seq': -1,
                'last_time': 0,
                'received_seqs': set(),
                'reorder_buffer': []
            }

        state = device_state[device_id]

        # Check for duplicate
        is_duplicate = seq_num in state['received_seqs']
        if is_duplicate:
            duplicate_count += 1

        # Check for delayed packets (reordering)
        is_delayed = False
        if state['last_seq'] != -1 and seq_num < state['last_seq']:
            is_delayed = True
            print(f"[Device {device_id}] Delayed packet detected: seq={seq_num} (last: {state['last_seq']}, timestamp diff: {timestamp - state['last_time']}s)")
            # Add to reorder buffer
            state['reorder_buffer'].append({
                'seq_num': seq_num,
                'timestamp': timestamp,
                'arrival_time': arrival_time
            })

        # Process reorder buffer if we have newer packets
        if state['reorder_buffer'] and not is_duplicate:
            reordered = reorder_by_timestamp(state['reorder_buffer'])
            for pkt in reordered:
                if pkt['seq_num'] > state['last_seq']:
                    state['last_seq'] = pkt['seq_num']
                    state['reorder_buffer'].remove(pkt)
                    print(f"[Device {device_id}] Reordered packet #{pkt['seq_num']} by timestamp")

        # Check for gap (packet loss)
        has_gap = False
        if state['last_seq'] != -1 and seq_num > state['last_seq'] + 1:
            gap_size = seq_num - state['last_seq'] - 1
            sequence_gap_count += gap_size
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
        log_to_csv(device_id, seq_num, timestamp, arrival_time, is_duplicate, has_gap, checksum_valid)

        # Print message info
        msg_type_str = "DATA" if msg_type == MSG_DATA else "HEARTBEAT" if msg_type == MSG_HEARTBEAT else "UNKNOWN"
        print(f"[Device {device_id}] Received {msg_type_str} - Seq: {seq_num}, From: {address}")

        # Measure elapsed processing time
        processing_end = time.perf_counter()
        total_processing_time += (processing_end - processing_start)

        # Print metrics every 50 packets
        if total_packets % 50 == 0:
            print(f"\n=== Metrics (packets received: {total_packets}) ===")
            duplicate_rate = duplicate_count / total_packets if total_packets else 0
            cpu_ms_per_report = (total_processing_time / total_packets * 1000) if total_packets else 0
            print(f"  packets_received: {total_packets}")
            print(f"  duplicate_count: {duplicate_count}")
            print(f"  duplicate_rate: {duplicate_rate:.2%}")
            print(f"  sequence_gap_count: {sequence_gap_count}")
            print(f"  cpu_ms_per_report: {cpu_ms_per_report:.3f} ms")
            print(f"==================================\n")

    except KeyboardInterrupt:
        print("\nServer shutting down...")
        print(f"\nFinal Metrics:")
        print(f"  Total packets received: {total_packets}")
        print(f"  Total duplicates: {duplicate_count}")
        print(f"  Total sequence gaps: {sequence_gap_count}")
        break
    except Exception as e:
        print(f"Error: {e}")

def detect_loss_rate(device_id, gap_packets, total_packets, threshold=0.05):
    """Check if packet loss rate exceeds threshold"""
    if total_packets == 0:
        print(f"[Device {device_id}] No packets received, cannot compute loss rate")
        return

    loss_rate = gap_packets / total_packets
    if loss_rate > threshold:
        print(f"[Device {device_id}] Detected unacceptable packet loss rate: {loss_rate:.2%}")
    else:
        print(f"[Device {device_id}] Packet loss rate is acceptable: {loss_rate:.2%}")



def check_flags(flags: int):
    if flags & FLAG_ACK:
        print("ACK flag set")
    if flags & FLAG_ERROR:
        print("Error flag detected")
    # Add more as needed

# Close server socket
server_socket.close()
