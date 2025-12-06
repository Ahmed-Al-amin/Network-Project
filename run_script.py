#!/usr/bin/env python3
"""
IoT Telemetry Protocol - Main Test Runner
Orchestrates server and client processes and analyzes results
"""

import subprocess
import time
import os
import sys
import csv
from collections import defaultdict

class TestRunner:
    def __init__(self, duration=20):
        self.duration = duration
        self.server_process = None
        self.client_process = None
        self.csv_file = "telemetry_log.csv"
        self.packet_log = "packet_log.txt"
        
    def cleanup_logs(self):
        """Remove old log files"""
        for f in [self.csv_file, self.packet_log]:
            if os.path.exists(f):
                os.remove(f)
                print(f"[*] Cleaned up {f}")
    
    def start_server(self):
        """Start the server process"""
        try:
            self.server_process = subprocess.Popen(
                [sys.executable, 'Server.py'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            print(f"[+] Server started with PID: {self.server_process.pid}")
            time.sleep(1)  # Let server bind to socket
            return True
        except Exception as e:
            print(f"[-] Failed to start server: {e}")
            return False
    
    def start_client(self):
        """Start the client process"""
        try:
            self.client_process = subprocess.Popen(
                [sys.executable, 'Client.py'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            print(f"[+] Client started with PID: {self.client_process.pid}")
            return True
        except Exception as e:
            print(f"[-] Failed to start client: {e}")
            return False
    
    def stop_processes(self):
        """Gracefully stop both processes"""
        if self.client_process:
            try:
                print(f"[*] Stopping Client (PID: {self.client_process.pid})")
                self.client_process.terminate()
                self.client_process.wait(timeout=5)
                print("[+] Client stopped")
            except subprocess.TimeoutExpired:
                self.client_process.kill()
                print("[!] Client killed (timeout)")
            except Exception as e:
                print(f"[-] Error stopping client: {e}")
        
        if self.server_process:
            try:
                print(f"[*] Stopping Server (PID: {self.server_process.pid})")
                self.server_process.terminate()
                self.server_process.wait(timeout=5)
                print("[+] Server stopped")
            except subprocess.TimeoutExpired:
                self.server_process.kill()
                print("[!] Server killed (timeout)")
            except Exception as e:
                print(f"[-] Error stopping server: {e}")
    
    def analyze_results(self):
        """Analyze test results from CSV"""
        if not os.path.exists(self.csv_file):
            print("[-] No telemetry log found - test may have failed")
            return
        
        try:
            stats = {
                'total_packets': 0,
                'duplicates': 0,
                'gaps': 0,
                'checksum_errors': 0,
                'devices': defaultdict(lambda: {'packets': 0, 'duplicates': 0})
            }
            
            with open(self.csv_file, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    stats['total_packets'] += 1
                    dev_id = row.get('device_id')
                    
                    if dev_id:
                        stats['devices'][dev_id]['packets'] += 1
                    
                    if row.get('duplicate_flag') == '1':
                        stats['duplicates'] += 1
                        if dev_id:
                            stats['devices'][dev_id]['duplicates'] += 1
                    
                    if row.get('gap_flag') == '1':
                        stats['gaps'] += 1
                    
                    if row.get('checksum_valid') == '0':
                        stats['checksum_errors'] += 1
            
            # Print results
            print("\n" + "="*70)
            print("TEST RESULTS SUMMARY")
            print("="*70)
            print(f"\n[GENERAL STATISTICS]")
            print(f"  Total packets received: {stats['total_packets']}")
            print(f"  Unique devices: {len(stats['devices'])}")
            
            print(f"\n[DATA INTEGRITY]")
            dup_rate = (stats['duplicates'] / stats['total_packets'] * 100) if stats['total_packets'] > 0 else 0
            gap_rate = (stats['gaps'] / stats['total_packets'] * 100) if stats['total_packets'] > 0 else 0
            err_rate = (stats['checksum_errors'] / stats['total_packets'] * 100) if stats['total_packets'] > 0 else 0
            
            print(f"  Duplicate packets: {stats['duplicates']} ({dup_rate:.2f}%)")
            print(f"  Sequence gaps: {stats['gaps']} ({gap_rate:.2f}%)")
            print(f"  Checksum errors: {stats['checksum_errors']} ({err_rate:.2f}%)")
            
            if stats['devices']:
                print(f"\n[PER-DEVICE BREAKDOWN]")
                for dev_id in sorted(stats['devices'].keys()):
                    dev = stats['devices'][dev_id]
                    dup_pct = (dev['duplicates'] / dev['packets'] * 100) if dev['packets'] > 0 else 0
                    print(f"  Device {dev_id}: {dev['packets']} packets, {dev['duplicates']} dupes ({dup_pct:.2f}%)")
            
            # Pass/fail assessment
            print(f"\n[ASSESSMENT]")
            if dup_rate < 1.0 and err_rate == 0:
                print("  ✓ TEST PASSED - All quality metrics within acceptable range")
            else:
                print("  ✗ TEST FAILED - Quality metrics exceeded thresholds")
                if dup_rate >= 1.0:
                    print(f"    - Duplicate rate {dup_rate:.2f}% exceeds 1% threshold")
                if err_rate > 0:
                    print(f"    - Checksum errors detected")
            
            print("="*70 + "\n")
        
        except Exception as e:
            print(f"[-] Error analyzing results: {e}")
    
    def run(self):
        """Execute the complete test"""
        print("\n" + "="*70)
        print("IoT TELEMETRY PROTOCOL - BASELINE TEST")
        print("="*70)
        print(f"\nTest Duration: {self.duration} seconds")
        print("="*70 + "\n")
        
        # Cleanup old logs
        self.cleanup_logs()
        
        # Start server
        if not self.start_server():
            print("[-] Failed to start server - aborting test")
            return 1
        
        # Start client
        if not self.start_client():
            print("[-] Failed to start client - stopping server")
            self.stop_processes()
            return 1
        
        # Run test
        print(f"\n[*] Test running for {self.duration} seconds...")
        try:
            time.sleep(self.duration)
        except KeyboardInterrupt:
            print("\n[!] Test interrupted by user")
        
        print("[*] Test duration complete")
        
        # Stop processes
        print()
        self.stop_processes()
        
        # Analyze results
        time.sleep(1)  # Give server time to write logs
        print()
        self.analyze_results()
        
        print("[+] Test finished - check 'telemetry_log.csv' for detailed results")
        print("[+] Check 'packet_log.txt' for client transmission details\n")
        
        return 0

def main():
    """Main entry point"""
    duration = 20
    
    if len(sys.argv) > 1:
        try:
            duration = int(sys.argv[1])
        except ValueError:
            print(f"Usage: {sys.argv[0]} [duration_seconds]")
            print(f"Using default duration: {duration}s")
    
    runner = TestRunner(duration=duration)
    return runner.run()

if __name__ == "__main__":
    sys.exit(main())