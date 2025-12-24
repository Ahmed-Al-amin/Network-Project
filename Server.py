import socket
import csv
import struct
import argparse
import time
from collections import deque
from datetime import datetime
from time import process_time 
from time import perf_counter
import signal  # <--- ADD THIS



# ==========================================
# Configuration & Constants
# ==========================================
HEADER_FORMAT = '!HHIB'  # DeviceID(2), SeqNum(2), Timestamp(4), MsgType(1)
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
SEQ_MAX = 65536          
WRAP_THRESHOLD = 30000   
VERSION = 1
# Reordering Settings
DEFAULT_FLUSH_THRESHOLD = 20      

# Message Types
MSG_INIT = 0x00
MSG_DATA = 0x01
MSG_HEARTBEAT = 0x02

# Dec 1, 2025 at 00:00:00 UTC (The Common Epoch)
TIMESTAMP_OFFSET = 1764547200

LIVENESS_TIMEOUT = 10.0  
SOCKET_TIMEOUT = 1.0    
SOURCE_PORT = 12000
OUTPUT_CSV = 'telemetry_log.csv' 

# ==========================================
# Helper Functions
# ==========================================
def compute_checksum(data: bytes) -> int:
    return sum(data) & 0xFFFF

def initialize_csv(filename):
    headers = [
        'device_id', 'seq', 'timestamp_raw', 'readable_time', 'arrival_time', 
        'duplicate_flag', 'gap_flag', 'gap_count',
        'latency_ms', 'jitter_ms', 'msg_type', 'payload_size', 
        'temp', 'humidity', 'voltage', 'cpu_ms'  # <--- Added sensor fields
    ]
    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
    print(f"[*] Log file initialized: {filename}")

def log_packet(filename, data_dict, t, h, v): # Added t, h, v parameters
    dt_object = datetime.fromtimestamp(data_dict['arrival_time'])
    readable_str = dt_object.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

    server_relative_time = data_dict['arrival_time'] - TIMESTAMP_OFFSET
    server_arrival_ms = int(server_relative_time * 1000) & 0xFFFFFFFF

    with open(filename, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            data_dict['device_id'],
            data_dict['seq'],
            data_dict['timestamp_sent'], 
            readable_str,
            server_arrival_ms,
            int(data_dict['duplicate']),
            int(data_dict['gap_detected']),
            data_dict['gap_count'],
            f"{data_dict['latency']:.3f}",
            f"{data_dict['jitter']:.3f}",
            data_dict['msg_type'],
            data_dict['payload_len'],
            round(t, 2),  # Individual reading
            round(h, 2),  # Individual reading
            round(v, 2),  # Individual reading
            f"{data_dict.get('cpu_ms', 0):.6f}"
        ])


def process_and_log_packet(state, packet_data, filename):
    t0 = perf_counter() 
    seq_num = packet_data['seq']
    device_id = packet_data['device_id']
    
    state['stats']['received'] += 1

    # --- Gap & Sequence Logic (Per Packet) ---
    gap_detected = False
    gap_count = 0
    
    if seq_num in state['processed_seqs']:
        packet_data['duplicate'] = True
        state['stats']['duplicates'] += 1
    else:
        state['processed_seqs'].append(seq_num)
        if state['last_processed_seq'] is not None:
            last = state['last_processed_seq']
            diff = seq_num - last
            if diff < -WRAP_THRESHOLD: 
                real_diff = seq_num + SEQ_MAX - last
                if real_diff > 1:
                    gap_detected = True
                    gap_count = real_diff - 1
            elif diff > 1:
                gap_detected = True
                gap_count = diff - 1
        state['last_processed_seq'] = seq_num

    packet_data['gap_detected'] = gap_detected
    packet_data['gap_count'] = gap_count
    if gap_detected:
        state['stats']['gaps'] += gap_count

    t1 = perf_counter()
    logic_cost_ms = (t1 - t0) * 1000 
    packet_data['cpu_ms'] = logic_cost_ms + packet_data.get('parse_cost_ms', 0)
    
    # --- "Explode" the Batch: Log each reading ---
    readings = packet_data.get('readings', [])
    
    if not readings: # Handle Heartbeats or empty data
        log_packet(filename, packet_data, 0.0, 0.0, 0.0)
    else:
        for r in readings:
            # r is a tuple (temp, hum, volt)
            log_packet(filename, packet_data, r[0], r[1], r[2])




# ==========================================
# Main Server Loop
# ==========================================
def main():


    # ==========================================
    # START OF NEW CODE
    # ==========================================
    def signal_handler(sig, frame):
        # This turns SIGTERM (kill command) into an exception
        # so your 'finally' block runs and saves the CSV.
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    # ==========================================
    # END OF NEW CODE
    # ==========================================


    
    parser = argparse.ArgumentParser(description='IoT Telemetry Server')
    parser.add_argument('--port', type=int, default=SOURCE_PORT, help='Server Port')
    parser.add_argument('--output', type=str, default=OUTPUT_CSV, help='CSV output file')
    parser.add_argument('--died_after', type=int, default=LIVENESS_TIMEOUT, help='consider the client dead after timeout (seconds)')
    parser.add_argument('--buffer', type=int, default=DEFAULT_FLUSH_THRESHOLD,help='Reordering buffer flush threshold')

    args = parser.parse_args()
    flush_threshold = args.buffer

    liveness_timeout_client = args.died_after

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.bind(('', args.port))
    server_socket.settimeout(SOCKET_TIMEOUT)
    initialize_csv(args.output)
    
    print(f"[*] Server listening on 0.0.0.0:{args.port} with Reordering Logic")

    # State now includes 'stats'
    devices_state = {}

    try:
        while True:

            current_real_time = time.time()
            
            # Liveness Check
            for d_id, d_state in devices_state.items():
                if d_state.get('status_alive', True): 
                    time_since_last = current_real_time - d_state.get('last_seen', current_real_time)
                    
                    if time_since_last > liveness_timeout_client:
                        print(f"[!] ALERT: Device {d_id} is OFFLINE (No signal for {time_since_last:.1f}s)")
                        d_state['status_alive'] = False
                                                # --- NEW: FORCE FLUSH BUFFER FOR DEAD DEVICE ---
                        if len(d_state['buffer']) > 0:
                            print(f"[*] Flushing {len(d_state['buffer'])} stuck packets for Device {d_id}...")
                            # 1. Sort what we have
                            d_state['buffer'].sort(key=lambda x: x['timestamp_sent'])
                            
                            # 2. Process all of them
                            while d_state['buffer']:
                                pkt = d_state['buffer'].pop(0)
                                pkt['status'] = 'Flushed (Timeout)'
                                process_and_log_packet(d_state, pkt, args.output)

            # 1. Receive
            try:
                data, addr = server_socket.recvfrom(1024)
            except socket.timeout:
                continue
            except Exception as e:
                print(f"[!] Socket Error: {e}")
                break

            arrival_time = time.time()

            # --- START PARSE TIMER ---
            t_parse_start = perf_counter()
            #t_parse_start = process_time()
                            
            # 2. Parse
            if len(data) < HEADER_SIZE + 2: continue
            
            try:
                header = data[:HEADER_SIZE]
                device_id, seq_num, ts_sent, msg_version_byte = struct.unpack(HEADER_FORMAT, header)
                
                # Extract Version: Shift right by 4 bits to get the top half
                packet_version = (msg_version_byte >> 4) & 0x0F 
                
                # Extract MsgType: AND with 0x0F (00001111) to get the bottom half
                msg_type = msg_version_byte & 0x0F

                # Checksum
                checksum = struct.unpack('!H', data[HEADER_SIZE:HEADER_SIZE+2])[0]
                if compute_checksum(header + data[HEADER_SIZE+2:]) != checksum:
                    print(f"[!] Checksum fail from {addr}")
                    continue
            except struct.error:
                continue

            # --- STOP PARSE TIMER ---
            t_parse_end = perf_counter()
            #t_parse_end = process_time()
            parse_cost_ms = (t_parse_end - t_parse_start) * 1000

            # 3. Initialize State
            if device_id not in devices_state:
                devices_state[device_id] = {
                    'buffer': [], 
                    'last_latency': 0.0,
                    'last_processed_seq': None,
                    'processed_seqs': deque(maxlen=500),
                    'last_seen': arrival_time,
                    'status_alive': True,
                    # --- NEW STATS COUNTERS ---
                    'stats': {'received': 0, 'duplicates': 0, 'gaps': 0}
                }
            
            state = devices_state[device_id]
            state['last_seen'] = arrival_time

            if state['status_alive'] == False:
                 print(f"[*] ALERT: Device {device_id} is BACK ONLINE!")
            state['status_alive'] = True

            
            if msg_type == MSG_INIT:
                print(f"[*] RESET: Received INIT from Device {device_id}. Clearing sequence history.")
                state['processed_seqs'].clear()
                state['last_processed_seq'] = None
                state['stats']['duplicates'] = 0 # Optional: reset stats for the new session
            

            

            # --- PAYLOAD PARSING ---
            payload = data[HEADER_SIZE+2:]
            readings_list = []
            if msg_type == MSG_DATA and len(payload) > 0:
                try:
                    count = struct.unpack('!B', payload[:1])[0]
                    for i in range(count):
                        start_idx = 1 + (i * 12)
                        end_idx = start_idx + 12
                        if len(payload) >= end_idx:
                            chunk = payload[start_idx:end_idx]
                            t_val, h_val, v_val = struct.unpack('!fff', chunk)
                            readings_list.append((t_val, h_val, v_val))
                except struct.error:
                    print(f"[!] Payload parse error from {device_id}")

            # 4. Pre-Calculation
            relative_arrival = arrival_time - TIMESTAMP_OFFSET
            arrival_ms_masked = int(relative_arrival * 1000) & 0xFFFFFFFF
            latency_ms = arrival_ms_masked - ts_sent
            if latency_ms < -2147483648: latency_ms += 4294967296
            latency_ms = max(0, latency_ms)

            jitter = 0.0
            if state['last_latency'] > 0:
                jitter = abs(latency_ms - state['last_latency'])
            state['last_latency'] = latency_ms

            # 5. Add to Buffer
            packet_entry = {
                'device_id': device_id,
                'seq': seq_num,
                'timestamp_sent': ts_sent,      
                'arrival_time': arrival_time,
                'latency': latency_ms,
                'jitter': jitter,
                'duplicate': False,            
                'gap_detected': False,          
                'gap_count': 0,
                'msg_type': 'INIT' if msg_type == MSG_INIT else ('DATA' if msg_type == MSG_DATA else 'HEARTBEAT'),
                'payload_len': len(data) - HEADER_SIZE - 2,
                'readings': readings_list,
                'status': 'Buffered',
                'parse_cost_ms': parse_cost_ms
            }
            
            state['buffer'].append(packet_entry)
            
            # 6. Reordering Logic
            state['buffer'].sort(key=lambda x: x['timestamp_sent'])
            
            while len(state['buffer']) > flush_threshold:
                packet_to_process = state['buffer'].pop(0)
                process_and_log_packet(state, packet_to_process, args.output)

    except KeyboardInterrupt:
        print("\n[*] Interrupt received...")
    finally:
        print("[*] Flushing remaining buffers...")
        for dev_id, state in devices_state.items():
            state['buffer'].sort(key=lambda x: x['timestamp_sent'])
            for pkt in state['buffer']:
                pkt['status'] = 'Flushed'
                process_and_log_packet(state, pkt, args.output)
        
        # --- PRINT SUMMARY REPORT ---
        print("\n" + "="*40)
        print(" FINAL SESSION SUMMARY")
        print("="*40)
        
        for dev_id, info in devices_state.items():
            stats = info['stats']
            total = stats['received']
            gaps = stats['gaps']
            dups = stats['duplicates']
            
            dup_rate = (dups / total * 100) if total > 0 else 0.0
            
            print(f"Device ID: {dev_id}")
            print(f"  - Total Packets Received:   {total}")
            print(f"  - Total Duplicates Detected: {dups}")
            print(f"  - Duplicate Rate:           {dup_rate:.2f}%")
            print(f"  - Total Missing Sequences:  {gaps}")
            print("-" * 20)
        
        print("[*] Server stopped.")
        server_socket.close()

if __name__ == "__main__":
    main()