import socket
import csv
import struct
import argparse
import time
from collections import deque

# ==========================================
# Configuration & Constants
# ==========================================
HEADER_FORMAT = '!HHIB'  # DeviceID(2), SeqNum(2), Timestamp(4), MsgType(1)
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
SEQ_MAX = 65536          # 2^16 for unsigned short wrap-around
WRAP_THRESHOLD = 30000   # Threshold to detect wrap-around vs massive gap

# Message Types
MSG_DATA = 0x01
MSG_HEARTBEAT = 0x02

# ==========================================
# Helper Functions
# ==========================================
def compute_checksum(data: bytes) -> int:
    """Compute 16-bit checksum."""
    return sum(data) & 0xFFFF

def initialize_csv(filename):
    """Creates the CSV file with the required headers."""
    headers = [
        'device_id', 'seq', 'timestamp_sent', 'arrival_time',
        'duplicate_flag', 'gap_flag', 'gap_count',
        'latency_ms', 'jitter_ms', 'msg_type', 'payload_size'
    ]
    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
    print(f"[*] Log file initialized: {filename}")

def log_packet(filename, data_dict):
    """Appends a packet record to the CSV."""
    with open(filename, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            data_dict['device_id'],
            data_dict['seq'],
            data_dict['timestamp_sent'],
            f"{data_dict['arrival_time']:.6f}",
            int(data_dict['duplicate']),
            int(data_dict['gap_detected']),
            data_dict['gap_count'],
            f"{data_dict['latency']:.3f}",
            f"{data_dict['jitter']:.3f}",
            data_dict['msg_type'],
            data_dict['payload_len']
        ])

# ==========================================
# Core Logic
# ==========================================
def main():
    parser = argparse.ArgumentParser(description='IoT Telemetry Server')
    parser.add_argument('--port', type=int, default=12000, help='UDP Port to bind')
    parser.add_argument('--output', type=str, default='telemetry_log.csv', help='CSV Output file')
    args = parser.parse_args()

    # Setup Socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.bind(('', args.port))
    
    # Initialize Log
    initialize_csv(args.output)
    
    print(f"[*] Server listening on 0.0.0.0:{args.port}")
    print(f"[*] Press Ctrl+C to stop.")

    # State Management
    devices_state = {}

    try:
        while True:
            # 1. Receive Data
            data, addr = server_socket.recvfrom(1024)
            arrival_time = time.time() # Full precision system time
            
            # 2. Basic Validation
            if len(data) < HEADER_SIZE + 2:
                print(f"[!] Ignored too small packet from {addr}")
                continue

            # 3. Parse Header
            try:
                header_data = data[:HEADER_SIZE]
                device_id, seq_num, ts_sent, msg_type = struct.unpack(HEADER_FORMAT, header_data)
                
                # Checksum Verification
                received_checksum = struct.unpack('!H', data[HEADER_SIZE:HEADER_SIZE+2])[0]
                payload = data[HEADER_SIZE+2:]
                
                computed = compute_checksum(header_data + payload)
                if computed != received_checksum:
                    print(f"[!] Checksum Error Device {device_id}: Exp {received_checksum} != Calc {computed}")
                    continue 

            except struct.error:
                print(f"[!] Struct unpacking error from {addr}")
                continue

            # 4. Initialize State
            if device_id not in devices_state:
                devices_state[device_id] = {
                    'last_seq': None,
                    'last_latency': 0.0,
                    'recent_seqs': deque(maxlen=100) 
                }
                print(f"[*] New Device Detected: {device_id}")

            state = devices_state[device_id]
            
            # 5. Analysis Logic (Gaps, Duplicates, Wrap-around)
            is_duplicate = False
            gap_detected = False
            gap_count = 0
            
            if seq_num in state['recent_seqs']:
                is_duplicate = True
                print(f"[Device {device_id}] Duplicate detected: Seq {seq_num}")
            else:
                state['recent_seqs'].append(seq_num)

            if state['last_seq'] is not None and not is_duplicate:
                last = state['last_seq']
                diff = seq_num - last

                # Wrap Around
                if diff < -WRAP_THRESHOLD: 
                    real_diff = seq_num + SEQ_MAX - last
                    if real_diff > 1:
                        gap_detected = True
                        gap_count = real_diff - 1
                        print(f"[Device {device_id}] Wrap-around Gap detected! Lost: {gap_count}")
                    state['last_seq'] = seq_num 

                # Out of order
                elif diff < 0:
                    print(f"[Device {device_id}] Out-of-order packet: {seq_num} (Last: {last})")

                # Normal Gap or In-Order
                else:
                    if diff > 1:
                        gap_detected = True
                        gap_count = diff - 1
                        print(f"[Device {device_id}] Gap detected: {gap_count} packets lost (Seq {last}->{seq_num})")
                    state['last_seq'] = seq_num

            elif state['last_seq'] is None:
                state['last_seq'] = seq_num

            # 6. Performance Metrics (FIXED LATENCY CALCULATION)
            # ---------------------------------------------------------
            # Convert server arrival time to the same format as client:
            # Milliseconds, truncated to 32-bit (to match Client's & 0xFFFFFFFF)
            arrival_ms_masked = int(arrival_time * 1000) & 0xFFFFFFFF
            
            # Now both are comparable 32-bit integers
            latency_ms = arrival_ms_masked - ts_sent
            
            # Handle edge case: small clock skew making it negative on localhost
            if latency_ms < 0:
                 # If negative, it might mean slight clock skew or wrap-around boundary. 
                 # For localhost, we can clamp to 0 or leave as is to show skew.
                 # Let's handle the wrap-around case (server wrapped, client didn't yet)
                 if latency_ms < -2147483648: 
                     latency_ms += 4294967296
                 else:
                     # Just small skew, keep it or clamp to 0 for cleaner logs
                     latency_ms = max(0, latency_ms)

            # Jitter Calculation
            jitter = 0.0
            if state['last_latency'] > 0:
                jitter = abs(latency_ms - state['last_latency'])
            
            state['last_latency'] = latency_ms
            # ---------------------------------------------------------

            # 7. Log to CSV
            log_entry = {
                'device_id': device_id,
                'seq': seq_num,
                'timestamp_sent': ts_sent,
                'arrival_time': arrival_time, # Keep full precision for reference
                'duplicate': is_duplicate,
                'gap_detected': gap_detected,
                'gap_count': gap_count,
                'latency': latency_ms,      # Now meaningful (e.g., 5.0 ms)
                'jitter': jitter,
                'msg_type': 'DATA' if msg_type == MSG_DATA else 'HEARTBEAT',
                'payload_len': len(payload)
            }
            
            log_packet(args.output, log_entry)
            
            # Optional: Print info
            if total_packets := len(state['recent_seqs']): # Just to show some activity
                 pass 

    except KeyboardInterrupt:
        print("\n[*] Server shutting down...")
        server_socket.close()
    except Exception as e:
        print(f"[!] Critical Error: {e}")
        server_socket.close()

if __name__ == "__main__":
    main()