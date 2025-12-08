import socket
import csv
import struct
import argparse
import time
from collections import deque
from datetime import datetime

# ==========================================
# Configuration & Constants
# ==========================================
HEADER_FORMAT = '!HHIB'  # DeviceID(2), SeqNum(2), Timestamp(4), MsgType(1)
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
SEQ_MAX = 65536          
WRAP_THRESHOLD = 30000   

# Reordering Settings
REORDER_BUFFER_SIZE = 20  # Keep X packets in buffer to allow sorting
FLUSH_THRESHOLD = 10      # Process packets when buffer exceeds this count

# Message Types
MSG_DATA = 0x01
MSG_HEARTBEAT = 0x02

# Dec 1, 2025 at 00:00:00 UTC (The Common Epoch)
TIMESTAMP_OFFSET = 1764547200

# ==========================================
# Helper Functions
# ==========================================
def compute_checksum(data: bytes) -> int:
    return sum(data) & 0xFFFF

def initialize_csv(filename):
    headers = [
        'device_id', 'seq', 'timestamp_raw', 'readable_time', 'arrival_time', # الترتيب الجديد
        'duplicate_flag', 'gap_flag', 'gap_count',
        'latency_ms', 'jitter_ms', 'msg_type', 'payload_size'
    ]
    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
    print(f"[*] Log file initialized: {filename}")

def log_packet(filename, data_dict):
    # 1. بنحسب الوقت المقروء (للبشر) زي ما هو
    dt_object = datetime.fromtimestamp(data_dict['arrival_time'])
    readable_str = dt_object.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

    # 2. (الجديد) بنحول وقت وصول السيرفر لنفس مرجع الكلاينت (مللي ثانية من بداية الشهر)
    # المعادلة: (وقت السيرفر - وقت البداية) * 1000
    server_relative_time = data_dict['arrival_time'] - TIMESTAMP_OFFSET
    server_arrival_ms = int(server_relative_time * 1000) & 0xFFFFFFFF

    with open(filename, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            data_dict['device_id'],
            data_dict['seq'],
            data_dict['timestamp_sent'], 
            readable_str,
            server_arrival_ms,           # <--- هنا التغيير: حطينا الرقم المعدل بدل الأصلي
            int(data_dict['duplicate']),
            int(data_dict['gap_detected']),
            data_dict['gap_count'],
            f"{data_dict['latency']:.3f}",
            f"{data_dict['jitter']:.3f}",
            data_dict['msg_type'],
            data_dict['payload_len']
        ])

def process_and_log_packet(state, packet_data, filename):
    """
    Core Logic: Gap detection and Logging happens HERE, 
    after the packet has been popped from the sorted buffer.
    """
    seq_num = packet_data['seq']
    device_id = packet_data['device_id']
    
    # --- Gap & Sequence Logic (Applied on Ordered Stream) ---
    gap_detected = False
    gap_count = 0
    
    # Check if this seq was already processed (Deep Duplicate Check)
    if seq_num in state['processed_seqs']:
        packet_data['duplicate'] = True
        packet_data['status'] = 'Duplicate (Buffered)'
        print(f"[Device {device_id}] Duplicate suppressed: Seq {seq_num}")
    else:
        state['processed_seqs'].append(seq_num)
        
        # Gap Logic against last PROCESSED sequence
        if state['last_processed_seq'] is not None:
            last = state['last_processed_seq']
            diff = seq_num - last

            # Wrap Around
            if diff < -WRAP_THRESHOLD: 
                real_diff = seq_num + SEQ_MAX - last
                if real_diff > 1:
                    gap_detected = True
                    gap_count = real_diff - 1
            
            # Normal Gap
            elif diff > 1:
                gap_detected = True
                gap_count = diff - 1
            
            # Note: Since we reordered, "diff < 0" shouldn't happen often 
            # unless a packet arrived WAY too late (outside buffer window).
            if diff < 0 and diff > -WRAP_THRESHOLD:
                 packet_data['status'] = 'Late-Arrival'

        state['last_processed_seq'] = seq_num

    packet_data['gap_detected'] = gap_detected
    packet_data['gap_count'] = gap_count
    
    # Log to CSV
    log_packet(filename, packet_data)
    
    if gap_detected:
         print(f"[Device {device_id}] GAP! Lost {gap_count} packets (Seq {seq_num})")

# ==========================================
# Main Server Loop
# ==========================================
def main():
    parser = argparse.ArgumentParser(description='IoT Telemetry Server')
    parser.add_argument('--port', type=int, default=12000)
    parser.add_argument('--output', type=str, default='telemetry_log.csv')
    args = parser.parse_args()

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.bind(('', args.port))
    initialize_csv(args.output)
    
    print(f"[*] Server listening on 0.0.0.0:{args.port} with Reordering Logic")

    # State: { device_id: { 'buffer': [], 'last_latency': 0.0, 'processed_seqs': deque, ... } }
    devices_state = {}

    try:
        while True:
 # 1. Receive
            data, addr = server_socket.recvfrom(1024)
                
            arrival_time = time.time()
            
            # 2. Parse
            if len(data) < HEADER_SIZE + 2: continue
            
            try:
                header = data[:HEADER_SIZE]
                device_id, seq_num, ts_sent, msg_type = struct.unpack(HEADER_FORMAT, header)
                
                # Checksum
                checksum = struct.unpack('!H', data[HEADER_SIZE:HEADER_SIZE+2])[0]
                if compute_checksum(header + data[HEADER_SIZE+2:]) != checksum:
                    print(f"[!] Checksum fail from {addr}")
                    continue
            except struct.error:
                continue

            # 3. Initialize State
            if device_id not in devices_state:
                devices_state[device_id] = {
                    'buffer': [], # The Reordering Buffer
                    'last_latency': 0.0,
                    'last_processed_seq': None,
                    'processed_seqs': deque(maxlen=500)
                }
            
            state = devices_state[device_id]
            
            # 4. Pre-Calculation (Network Stats must be calculated on ARRIVAL)
           # --- Latency Calculation with Custom Epoch ---
            # 1. Convert Server Arrival to Relative MS (Same as Client)
            relative_arrival = arrival_time - TIMESTAMP_OFFSET
            arrival_ms_masked = int(relative_arrival * 1000) & 0xFFFFFFFF
            
            # 2. Calculate Latency
            latency_ms = arrival_ms_masked - ts_sent
            
            # Fix negative wrap around
            if latency_ms < -2147483648: latency_ms += 4294967296
            latency_ms = max(0, latency_ms)

            jitter = 0.0
            if state['last_latency'] > 0:
                jitter = abs(latency_ms - state['last_latency'])
            state['last_latency'] = latency_ms

            # 5. Add to Buffer (Store raw data + metrics)
            packet_entry = {
                'device_id': device_id,
                'seq': seq_num,
                'timestamp_sent': ts_sent,      # Sort Key
                'arrival_time': arrival_time,
                'latency': latency_ms,
                'jitter': jitter,
                'duplicate': False,             # Calculated later
                'gap_detected': False,          # Calculated later
                'gap_count': 0,
                'msg_type': 'DATA' if msg_type == MSG_DATA else 'HEARTBEAT',
                'payload_len': len(data) - HEADER_SIZE - 2,
                'status': 'Buffered'
            }
            
            state['buffer'].append(packet_entry)
            
            # 6. Reordering Logic
            # Sort buffer by timestamp_sent (Client Time)
            state['buffer'].sort(key=lambda x: x['timestamp_sent'])
            
            # 7. Process Buffer if full (Flush logic)
            # We keep FLUSH_THRESHOLD packets in buffer to wait for latecomers
            while len(state['buffer']) > FLUSH_THRESHOLD:
                # Pop the oldest packet (smallest timestamp)
                packet_to_process = state['buffer'].pop(0)
                process_and_log_packet(state, packet_to_process, args.output)

    except KeyboardInterrupt:
        print("\n[*] Interrupt received...")
    finally:
        print("[*] Flushing remaining buffers...")
        # Flush all remaining packets in buffers
        for dev_id, state in devices_state.items():
            state['buffer'].sort(key=lambda x: x['timestamp_sent'])
            for pkt in state['buffer']:
                pkt['status'] = 'Flushed'
                process_and_log_packet(state, pkt, args.output)
        print("[*] Server stopped.")
        server_socket.close()

if __name__ == "__main__":
    main()