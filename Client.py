import socket
import time
import struct
import random
from datetime import datetime
import zlib
import logging
import os
from collections import deque

# Configuration
SERVER_HOST = 'localhost'
SERVER_PORT = 12000
DEVICE_ID = 1001  # Unique ID for this sensor
REPORTING_INTERVAL = 2  # seconds between reports
HEARTBEAT_INTERVAL = 5  # seconds between heartbeats when no data
BATCH_SIZE = 3  # Number of readings to batch in one packet
HEADER_FORMAT = '!HHIB'  # device_id(2), seq_num(2), timestamp(4), msg_type(1)
LOG_FILE = "packet_log.txt"
BATTERY_LOW_THRESHOLD = 3.3  # Volts threshold for low battery alert
# Message types
MSG_DATA = 0x01
MSG_HEARTBEAT = 0x02

# Create UDP socket
client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
print(f"Sensor {DEVICE_ID} starting...")

# Initialize sequence number
seq_num = 0


def log_packet(packet: bytes, seq_num: int, msg_type: int):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(LOG_FILE, 'a') as f:
        log_entry = f"{timestamp} SEQ:{seq_num} TYPE:{msg_type} SIZE:{len(packet)} BYTES DATA:{packet.hex()}\n"
        f.write(log_entry)

# Simulate battery voltage or read actual sensor input
def get_battery_level():
    # For simulation, generate random voltage near threshold
    voltage = round(random.uniform(3.0, 4.2), 2)
    return voltage

def check_battery_voltage(voltage):
    if voltage < BATTERY_LOW_THRESHOLD:
        print(f"Warning: Low Battery Level detected: {voltage}V")

# Compress sensor reading payload using zlib
def compress_payload(payload: bytes) -> bytes:
    return zlib.compress(payload)

# Create or reset UDP socket on network error
def safe_sendto(sock, packet, addr):
    try:
        sock.sendto(packet, addr)
    except OSError as e:
        print(f"Network error detected: {e}")
        print("Recreating socket...")
        sock.close()
        new_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        new_sock.settimeout(5)  # Optional timeout
        new_sock.sendto(packet, addr)
        return new_sock
    return sock


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

    # Compute checksum
    checksum = compute_checksum(header + payload)

    # Pack checksum (2 bytes, unsigned short)
    checksum_bytes = struct.pack('!H', checksum)

    return header + checksum_bytes + payload


def create_heartbeat_packet(device_id, seq_num):
    """Create a HEARTBEAT packet (no payload)"""
    timestamp = int(time.time())
    msg_type = MSG_HEARTBEAT

    # Pack header only (no payload for heartbeat)
    packet = struct.pack(HEADER_FORMAT, device_id, seq_num, timestamp, msg_type)

    # Compute checksum
    checksum = compute_checksum(packet)
    checksum_bytes = struct.pack('!H', checksum)

    return packet + checksum_bytes


def create_batch_data_packet(device_id, seq_num, readings_list):
    """Create a DATA packet with multiple sensor readings (batch)"""
    timestamp = int(time.time())
    msg_type = MSG_DATA

    # Pack header
    header = struct.pack(HEADER_FORMAT, device_id, seq_num, timestamp, msg_type)

    # Pack number of readings in batch (1 byte)
    num_readings = len(readings_list)
    num_readings_bytes = struct.pack('!B', num_readings)

    # Pack each reading
    payload_readings = b''
    for readings in readings_list:
        payload_readings += struct.pack('!fff',
                                       readings['temperature'],
                                       readings['humidity'],
                                       readings['voltage'])

    payload = num_readings_bytes + payload_readings

    # Compute checksum
    checksum = compute_checksum(header + payload)
    checksum_bytes = struct.pack('!H', checksum)

    return header + checksum_bytes + payload

# Dictionary to store the last processed sequence number for each device
last_seq_num = {}

def discard_duplicates_outdated(device_id, seq_num, timestamp, max_age_sec=60):
    """
    Returns True if the packet is new (not a duplicate or outdated) and should be processed.
    Returns False if the packet is a duplicate or outdated.

    Parameters:
    - device_id: unique identifier of the device
    - seq_num: sequence number of the incoming packet
    - timestamp: timestamp included in the packet (Unix epoch seconds)
    - max_age_sec: maximum allowed age of packet in seconds (default 60 seconds)
    """
    current_time = int(time.time())

    # Discard if the packet is too old
    if current_time - timestamp > max_age_sec:
        return False

    # Discard if this sequence number has already been processed or is older
    if device_id in last_seq_num and seq_num <= last_seq_num[device_id]:
        return False

    # Update last processed sequence number for this device
    last_seq_num[device_id] = seq_num
    return True


def compute_checksum(data: bytes) -> int:
    """
    Compute 16-bit checksum by summing all bytes and returning the lower 16 bits.
    """
    checksum = sum(data) & 0xFFFF
    return checksum

def verify_checksum(header: bytes, payload: bytes, received_checksum: int) -> bool:
    """
    Recomputes checksum and compares it to the received value.
    """
    computed = compute_checksum(header + payload)
    return computed == received_checksum

FLAG_ACK = 0x01
FLAG_ERROR = 0x02
FLAG_CUSTOM = 0x04

def check_flags(flags: int):
    if flags & FLAG_ACK:
        print("ACK flag set")
    if flags & FLAG_ERROR:
        print("Error flag detected")
    # Add more as needed


def verify_checksum(header: bytes, payload: bytes, received_checksum: int) -> bool:
    """
    Recomputes checksum and compares it to the received value.
    """
    computed = compute_checksum(header + payload)
    return computed == received_checksum


def generate_sensor_readings():
    """Simulate sensor readings"""
    return {
        'temperature': round(random.uniform(20.0, 30.0), 2),  # Celsius
        'humidity': round(random.uniform(30.0, 70.0), 2),  # Percentage
        'voltage': round(random.uniform(3.0, 5.0), 2)  # Volts
    }


# Setup logger for packet logging
logging.basicConfig(filename='packet_log.txt', level=logging.INFO, format='%(asctime)s %(message)s')

# Packet Loss Monitor Class to track sent packets and ACKs
class PacketLossMonitor:
    def __init__(self):
        self.sent_packets = set()  # Store sequence numbers of sent packets
        self.acknowledged_packets = set()  # Store sequence numbers of ACKed packets

    def record_packet_sent(self, seq_num):
        self.sent_packets.add(seq_num)

    def record_ack_received(self, seq_num):
        self.acknowledged_packets.add(seq_num)

    def get_lost_packets(self):
        # Packets sent but no ACK received
        lost_packets = self.sent_packets - self.acknowledged_packets
        return sorted(lost_packets)

    def report_loss_stats(self):
        lost = len(self.get_lost_packets())
        sent = len(self.sent_packets)
        loss_rate = (lost / sent * 100) if sent > 0 else 0.0
        return {
            'packets_sent': sent,
            'packets_lost': lost,
            'loss_rate_percent': loss_rate
        }

class NetworkStats:
    def __init__(self, window_size=100):
        # Store last N latency measurements to calculate jitter
        self.latencies = deque(maxlen=window_size)
        self.bytes_sent = 0
        self.packets_sent = 0
        self.start_time = time.time()
        self.last_latency = None

    def record_send(self, packet_size_bytes, send_time=None):
        """Record packet sent, packet_size_bytes is length of packet in bytes"""
        self.bytes_sent += packet_size_bytes
        self.packets_sent += 1
        if send_time is None:
            send_time = time.time()
        self.last_send_time = send_time

    def record_latency(self, latency_sec):
        """Record latency in seconds from send to ACK or simulated response"""
        self.latencies.append(latency_sec)

    def average_latency(self):
        if not self.latencies:
            return 0.0
        return sum(self.latencies) / len(self.latencies)

    def jitter(self):
        """Calculate jitter as average absolute difference between consecutive latencies"""
        if len(self.latencies) < 2:
            return 0.0
        diffs = [abs(self.latencies[i] - self.latencies[i-1]) for i in range(1, len(self.latencies))]
        return sum(diffs) / len(diffs)

    def throughput(self):
        """Calculate average throughput in bytes per second"""
        elapsed = time.time() - self.start_time
        if elapsed <= 0:
            return 0.0
        return self.bytes_sent / elapsed

    def report(self):
        """Return a dict of current stats"""
        return {
            'avg_latency_ms': self.average_latency() * 1000,
            'jitter_ms': self.jitter() * 1000,
            'throughput_bps': self.throughput() * 8  # Convert bytes/sec to bits/sec
        }




# Main send loop
stats = NetworkStats()
reading_batch = []

try:
    last_data_time = 0

    while True:
        current_time = time.time()

        # Check if we should send a new data packet
        if current_time - last_data_time >= REPORTING_INTERVAL:
            # Generate sensor reading
            reading = generate_sensor_readings()
            check_battery_voltage(reading['voltage'])
            reading_batch.append(reading)

            # Send batch if it's full or time to send
            if len(reading_batch) >= BATCH_SIZE:
                # Create BATCH DATA packet
                packet = create_batch_data_packet(DEVICE_ID, seq_num, reading_batch)

                # Send packet
                client_socket = safe_sendto(client_socket, packet, (SERVER_HOST, SERVER_PORT))
                log_packet(packet, seq_num, MSG_DATA)
                stats.record_send(len(packet))
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Sent BATCH DATA #{seq_num} ({len(reading_batch)} readings) - "
                      f"Avg Temp: {sum(r['temperature'] for r in reading_batch)/len(reading_batch):.1f}°C")

                reading_batch = []
                last_data_time = current_time
                seq_num += 1

        elif current_time - last_data_time >= HEARTBEAT_INTERVAL:
            # If we have buffered readings but haven't reached batch size, send them
            if reading_batch:
                packet = create_batch_data_packet(DEVICE_ID, seq_num, reading_batch)
                client_socket = safe_sendto(client_socket, packet, (SERVER_HOST, SERVER_PORT))
                log_packet(packet, seq_num, MSG_DATA)
                stats.record_send(len(packet))
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Sent PARTIAL BATCH DATA #{seq_num} ({len(reading_batch)} readings)")
                reading_batch = []
                last_data_time = current_time
                seq_num += 1
            else:
                # Send HEARTBEAT if no data for a while
                packet = create_heartbeat_packet(DEVICE_ID, seq_num)
                client_socket = safe_sendto(client_socket, packet, (SERVER_HOST, SERVER_PORT))
                log_packet(packet, seq_num, MSG_HEARTBEAT)
                stats.record_send(len(packet))
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Sent HEARTBEAT #{seq_num}")
                last_data_time = current_time
                seq_num += 1

        # Sleep briefly before next iteration
        time.sleep(0.1)


except KeyboardInterrupt:
    print(f"\n\nSensor {DEVICE_ID} shutting down...")
    print(f"Total packets sent: {seq_num}")
    print(f"Network Statistics:")
    print(f"  Average Latency: {stats.average_latency()*1000:.2f} ms")
    print(f"  Jitter: {stats.jitter()*1000:.2f} ms")
    print(f"  Throughput: {stats.throughput()*8:.2f} bps")
    client_socket.close()
except Exception as e:
    print(f"Error: {e}")
    client_socket.close()
