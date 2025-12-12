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
REPORTING_INTERVAL = 1.0  # Seconds
HEARTBEAT_INTERVAL = 5.0  # Seconds
MAX_PAYLOAD_SIZE = 200    # Bytes
BATCH_SIZE = 5            # Readings per packet

# Protocol Definition
# Header: DeviceID(2) + SeqNum(2) + Timestamp(4) + MsgType(1) = 9 Bytes
HEADER_FORMAT = '!HHIB'  
MSG_DATA = 0x01
MSG_HEARTBEAT = 0x02
PROTOCOL_VERSION = 1  # We are defining this as Version 1

# Dec 1, 2025 at 00:00:00 UTC (The Common Epoch)
TIMESTAMP_OFFSET = 1764547200

# Global state for smooth sensor simulation
sim_state = {'temp': 25.0, 'hum': 50.0, 'volt': 3.7}

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
    """
    Simulates a sensor that 'drifts' slowly rather than jumping randomly.
    """
    global sim_state
    
    # Drift the values slightly
    sim_state['temp'] += random.uniform(-0.5, 0.5)
    sim_state['hum']  += random.uniform(-1.0, 1.0)
    sim_state['volt'] += random.uniform(-0.05, 0.05)
    
    # Clamp values to realistic ranges
    sim_state['temp'] = max(15.0, min(35.0, sim_state['temp']))
    sim_state['hum']  = max(30.0, min(80.0, sim_state['hum']))
    sim_state['volt'] = max(3.3, min(4.2, sim_state['volt']))
    
    return {
        'temperature': round(sim_state['temp'], 2),
        'humidity': round(sim_state['hum'], 2),
        'voltage': round(sim_state['volt'], 2)
    }

def create_packet(device_id, seq_num, msg_type, payload_data=b''):
    """
    Generic function to create a packet with Header + Checksum + Payload.
    """
    # 1. Prepare Header Fields
    timestamp = get_current_time_ms()

    # Logic: Shift Version left by 4 bits, then OR it with the Message Type
    msg_version_byte = (PROTOCOL_VERSION << 4) | (msg_type & 0x0F)
    
    # 2. Pack Header (9 Bytes)
    header = struct.pack(HEADER_FORMAT, device_id, seq_num, timestamp, msg_version_byte)
    
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
    parser.add_argument('--id', type=int, default=DEVICE_ID, help='Device ID')
    parser.add_argument('--host', type=str, default=SERVER_HOST, help='Server IP')
    parser.add_argument('--port', type=int, default=SERVER_PORT, help='Server Port')
    parser.add_argument('--interval', type=float, default=REPORTING_INTERVAL, help='Reporting Interval (s)')
    parser.add_argument('--batch', type=int, default=1, help='Batch size (1 to N)') 
    parser.add_argument('--seed', type=int, default=None, help='Deterministic seed for RNG')
    parser.add_argument('--heartbeat', type=float, default=HEARTBEAT_INTERVAL, help='heartbeat interval (s)')

    args = parser.parse_args()

    # --- SEEDING LOGIC ---
    if args.seed is not None:
        random.seed(args.seed)
        print(f"[*] Mode: DETERMINISTIC (Seed: {args.seed})")
    else:
        seed_val = int(time.time() * 1000) % 1000000
        random.seed(seed_val)
        print(f"[*] Mode: RANDOM (Seed: {seed_val})")
    # ---------------------

    # Apply configuration
    device_id = args.id
    server_addr = (args.host, args.port)
    reporting_interval = args.interval
    batch_limit = args.batch
    heart_beat_interval = args.heartbeat

    # 2. Setup UDP Socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    print(f"[*] Sensor {device_id} started.")
    print(f"[*] Target: {server_addr}")
    print(f"[*] Interval: {reporting_interval}s | Batch Size: {batch_limit}")

    seq_num = 1
    readings_buffer = []

    # Independent Timers
    last_read_time = time.time()
    last_send_time = time.time()  

    try:
        while True:
            current_time = time.time()

            # --- Logic 1: Generate Data ---
            if (current_time - last_read_time >= reporting_interval):
                
                # 1. Read Sensor
                reading = generate_sensor_readings()
                readings_buffer.append(reading)
                last_read_time = current_time 
                
                # 2. Check if ready to send (Batch full?)
                if len(readings_buffer) >= batch_limit:
                    
                    # Prepare & Send
                    payload = prepare_batch_payload(readings_buffer)
                    
                    # Safety Check
                    if len(payload) > MAX_PAYLOAD_SIZE:
                        print(f"\n[!!!] FATAL ERROR: Payload size ({len(payload)}B) exceeds limit.")
                        break

                    packet = create_packet(device_id, seq_num, MSG_DATA, payload)
                    sock.sendto(packet, server_addr)
                    
                    print(f"[DATA] Seq:{seq_num} | Time:{current_time:.2f} | Size:{len(packet)}B")
                    
                    # Update Network Timer
                    last_send_time = current_time 
                    
                    readings_buffer = []
                    seq_num = (seq_num + 1) % 65536
            
            # --- Logic 2: Heartbeat ---
            # Check how long the network has been silent
            time_since_send = current_time - last_send_time
            
            # Send heartbeat ONLY if buffer empty and timer expired
            if (len(readings_buffer) == 0) and (time_since_send > heart_beat_interval):
                
                packet = create_packet(device_id, seq_num, MSG_HEARTBEAT)
                sock.sendto(packet, server_addr)
                print(f"[HEARTBEAT] Seq:{seq_num} | Alive")
                
                # Update Network Timer
                last_send_time = current_time
                seq_num = (seq_num + 1) % 65536

            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\n[!] Sensor shutting down.")
        sock.close()
    except Exception as e:
        print(f"\n[!] Error: {e}")
        sock.close()

if __name__ == "__main__":
    main()