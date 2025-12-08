import socket
import time
import struct
import random
from datetime import datetime
import argparse
import sys

# ==========================================
# Configuration & Constants
# ==========================================
SERVER_HOST = 'localhost'
SERVER_PORT = 12000
DEVICE_ID = 1001
REPORTING_INTERVAL = 1.0  # Seconds (Float for precision)
HEARTBEAT_INTERVAL = 5.0  # Seconds
MAX_PAYLOAD_SIZE = 200    # Bytes
BATCH_SIZE = 3            # Readings per packet

# Protocol Definition
# Header: DeviceID(2) + SeqNum(2) + Timestamp(4) + MsgType(1) = 9 Bytes
HEADER_FORMAT = '!HHIB'  
MSG_DATA = 0x01
MSG_HEARTBEAT = 0x02

# Dec 1, 2025 at 00:00:00 UTC (The Common Epoch)
TIMESTAMP_OFFSET = 1764547200

def get_current_time_ms():
    """
    Returns current time in milliseconds relative to TIMESTAMP_OFFSET.
    """
    current_time = time.time()
    # Subtract the offset to get "time since 2024"
    relative_time = current_time - TIMESTAMP_OFFSET
    return int(relative_time * 1000) & 0xFFFFFFFF

def compute_checksum(data: bytes) -> int:
    """Compute 16-bit checksum."""
    return sum(data) & 0xFFFF

def generate_sensor_readings():
    """Simulate sensor readings."""
    return {
        'temperature': round(random.uniform(20.0, 30.0), 2),
        'humidity': round(random.uniform(30.0, 70.0), 2),
        'voltage': round(random.uniform(3.0, 4.2), 2)
    }

def create_packet(device_id, seq_num, msg_type, payload_data=b''):
    """
    Generic function to create a packet with Header + Checksum + Payload.
    """
    # 1. Prepare Header Fields
    timestamp = get_current_time_ms()
    
    # 2. Pack Header (9 Bytes)
    header = struct.pack(HEADER_FORMAT, device_id, seq_num, timestamp, msg_type)
    
    # 3. Compute Checksum (Header + Payload)
    checksum = compute_checksum(header + payload_data)
    checksum_bytes = struct.pack('!H', checksum) # 2 Bytes
    
    # 4. Assemble Final Packet
    return header + checksum_bytes + payload_data

def prepare_batch_payload(readings_list):
    """
    Packs a list of readings into a binary payload.
    Format: [Count: 1B] + [Reading1: 12B] + [Reading2: 12B] ...
    """
    # Pack count
    count = len(readings_list)
    payload = struct.pack('!B', count)
    
    # Pack readings
    for r in readings_list:
        payload += struct.pack('!fff', r['temperature'], r['humidity'], r['voltage'])
        
    return payload

def main():
    # 1. Argument Parsing
    parser = argparse.ArgumentParser(description='IoT Telemetry Client')
    parser.add_argument('--id', type=int, default=1001, help='Device ID')
    parser.add_argument('--host', type=str, default='localhost', help='Server IP')
    parser.add_argument('--port', type=int, default=12000, help='Server Port')
    parser.add_argument('--interval', type=float, default=1.0, help='Reporting Interval (s)')
    parser.add_argument('--batch', type=int, default=1, help='Batch size (1 to N)') 
    parser.add_argument('--jam_at', type=int, default=0, help='Stop sending data after seq X')
    parser.add_argument('--jam_duration', type=float, default=0, help='Duration of jam in seconds')

    args = parser.parse_args()
    args = parser.parse_args()

    # Apply configuration
    device_id = args.id
    server_addr = (args.host, args.port)
    reporting_interval = args.interval
    batch_limit = args.batch

    # 2. Setup UDP Socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    print(f"[*] Sensor {device_id} started.")
    print(f"[*] Target: {server_addr}")
    print(f"[*] Interval: {reporting_interval}s | Batch Size: {batch_limit}")
    if args.jam_at > 0:
        print(f"[*] Simulation: Will JAM sensor at Seq {args.jam_at} for {args.jam_duration}s")

    seq_num = 1
    readings_buffer = []
    last_action_time = time.time()

    # Jamming State
    jam_start_time = 0
    is_jammed = False

    try:
        while True:
            current_time = time.time()
            time_since_last = current_time - last_action_time

            # --- JAMMING LOGIC START ---
            # Check if we reached the target sequence to jam
            if args.jam_at > 0 and seq_num >= args.jam_at and not is_jammed:
                print(f"\n[!] SIMULATING SENSOR FAILURE (JAMMING) for {args.jam_duration}s...")
                is_jammed = True
                jam_start_time = current_time
            
            # Check if jam duration is over
            if is_jammed:
                if (current_time - jam_start_time) > args.jam_duration:
                    print("[!] SENSOR RECOVERED. Resuming Data...")
                    is_jammed = False # Resume normal operation
                    args.jam_at = 0   # Disable jam so it doesn't happen again
                else:
                    # While jammed, we SKIP the Data Block to allow Heartbeat Block to trigger
                    pass 
            # --- JAMMING LOGIC END ---

            # --- Logic: Generate Data ---
            # We generate data periodically based on REPORTING_INTERVAL
            if not is_jammed and time_since_last >= reporting_interval:
                
                # 1. Read Sensor
                reading = generate_sensor_readings()
                readings_buffer.append(reading)
                last_action_time = current_time # Reset timer
                
                # 2. Check if ready to send (Batch full?)
                if len(readings_buffer) >= batch_limit:
                    
                    # Prepare Payload
                    payload = prepare_batch_payload(readings_buffer)
                    
                    # Safety Check: Max Payload Size
                    # Header(9) + Checksum(2) = 11 bytes overhead
                    # We want total packet <= 200 (or payload <= 200 depending on spec)
                    # Let's assume payload limit strictly.
                    if len(payload) > MAX_PAYLOAD_SIZE:
                        print(f"[!] Warning: Batch too large ({len(payload)}B). Sending anyway (or implement split logic).")
                    
                    # Create Packet
                    packet = create_packet(device_id, seq_num, MSG_DATA, payload)
                    
                    # Send
                    sock.sendto(packet, server_addr)
                    
                    print(f"[DATA] Seq:{seq_num} | Time:{current_time:.2f} | Size:{len(packet)}B | Readings:{len(readings_buffer)}")
                    
                    # Cleanup
                    readings_buffer = []
                    
                    # Increment Sequence (Handle Wrap Around)
                    seq_num = (seq_num + 1) % 65536
            
            # --- Logic: Heartbeat ---
            # If buffer is empty and time passed > HEARTBEAT_INTERVAL
            elif (len(readings_buffer) == 0) and (time_since_last > HEARTBEAT_INTERVAL):
                
                # Create Heartbeat (No payload)
                packet = create_packet(device_id, seq_num, MSG_HEARTBEAT)
                
                sock.sendto(packet, server_addr)
                print(f"[HEARTBEAT] Seq:{seq_num} | Alive")
                
                last_action_time = current_time
                seq_num = (seq_num + 1) % 65536

            # Small sleep to prevent 100% CPU usage
            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\n[!] Sensor shutting down.")
        sock.close()
    except Exception as e:
        print(f"\n[!] Error: {e}")
        sock.close()

if __name__ == "__main__":
    main()