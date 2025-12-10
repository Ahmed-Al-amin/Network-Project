import subprocess
import time
import os
import sys
import shutil
import signal

# ==========================================
# CONFIGURATION
# ==========================================
INTERFACE = "lo"
ROOT_DIR = "experiment_results"
SERVER_PORT = 12000
DURATION = 40  # Seconds per test

# ==========================================
# SYSTEM HELPERS
# ==========================================
def run_cmd(cmd, bg=False):
    """Executes shell command."""
    if bg:
        return subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.run(cmd, shell=True, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def cleanup():
    """Resets environment."""
    run_cmd(f"tc qdisc del dev {INTERFACE} root")
    run_cmd("pkill -f 'python3 Server.py'")
    run_cmd("pkill -f 'python3 Client.py'")
    run_cmd("pkill -f 'tcpdump'")
    time.sleep(1)

def print_header(title):
    print("\n" + "="*60)
    print(f"[*] {title}")
    print("="*60)

# ==========================================
# STANDARD TEST RUNNER
# ==========================================
def run_standard_test(section, name, interval, batch, netem, pcap=False, extra_args="", clients=1):
    print(f"\n--- Scenario: {name} ---")
    print(f"    Settings: Interval={interval}s | Batch={batch} | Clients={clients}")
    print(f"    Netem: {netem}")

    csv_path = f"{ROOT_DIR}/{section}/{name}.csv"
    pcap_path = f"{ROOT_DIR}/{section}/{name}.pcap"
    cleanup()

    if netem != "none":
        run_cmd(f"tc qdisc add dev {INTERFACE} root netem {netem}")

    if pcap:
        run_cmd(f"tcpdump -i {INTERFACE} udp port {SERVER_PORT} -w {pcap_path} -q", bg=True)
        time.sleep(1)

    server_proc = subprocess.Popen(["python3", "Server.py", "--output", csv_path])
    time.sleep(1)

    client_procs = []
    for i in range(clients):
        dev_id = 101 + i
        cmd = f"python3 Client.py --id {dev_id} --interval {interval} --batch {batch} {extra_args}"
        proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        client_procs.append(proc)
        
    for i in range(DURATION, 0, -1):
        sys.stdout.write(f"\r    Running... {i}s remaining ")
        sys.stdout.flush()
        time.sleep(1)
    print("\n    [+] Test Finished.")

    for proc in client_procs: proc.terminate()
    server_proc.terminate()
    try: server_proc.wait(timeout=2)
    except: server_proc.kill()
    cleanup()

def run_intermittent_test(section):
    name = "intermittent_tunnel"
    print(f"\n--- Scenario: {name} (The Tunnel) ---")
    csv_path = f"{ROOT_DIR}/{section}/{name}.csv"
    cleanup()

    server_proc = subprocess.Popen(["python3", "Server.py", "--output", csv_path])
    time.sleep(1)
    client_proc = subprocess.Popen("python3 Client.py --id 101 --interval 0.5", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print("    [1/3] Phase Normal (15s)...")
    time.sleep(15)
    print("    [2/3] CUTTING CONNECTION (Loss 100% for 15s)...")
    run_cmd(f"tc qdisc add dev {INTERFACE} root netem loss 100%")
    time.sleep(15)
    print("    [3/3] RESTORING CONNECTION (Normal for 15s)...")
    run_cmd(f"tc qdisc del dev {INTERFACE} root")
    time.sleep(15)

    client_proc.terminate()
    server_proc.terminate()
    cleanup()

# ==========================================
# CUSTOM MIXED BEHAVIOR TEST (SECTION 4)
# ==========================================
def run_mixed_behavior_test(section):
    name = "mixed_clients_complex"
    print(f"\n--- Scenario: {name} (The Ultimate Test) ---")
    print("    Network: Delay 30ms + Jitter 5ms + Loss 2%")
    print("    Client A (101): High Load (0.05s) + Jamming (Heartbeat test)")
    print("    Client B (102): Standard Traffic")
    print("    Client C (103): Standard Traffic")

    csv_path = f"{ROOT_DIR}/{section}/{name}.csv"
    pcap_path = f"{ROOT_DIR}/{section}/{name}.pcap"
    cleanup()

    # 1. Apply Global Network "messiness" (affects everyone)
    run_cmd(f"tc qdisc add dev {INTERFACE} root netem delay 30ms 5ms distribution normal loss 2%")

    # 2. Start PCAP
    run_cmd(f"tcpdump -i {INTERFACE} udp port {SERVER_PORT} -w {pcap_path} -q", bg=True)
    time.sleep(1)

    # 3. Start Server
    server_proc = subprocess.Popen(["python3", "Server.py", "--output", csv_path])
    time.sleep(1)

    # 4. Start Clients with DIFFERENT configurations
    procs = []
    
    # Client A: High Load + Jam at 20s
    cmd_a = "python3 Client.py --id 101 --interval 0.05 --jam_at 20 --jam_duration 10"
    procs.append(subprocess.Popen(cmd_a, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

    # Client B & C: Normal
    cmd_b = "python3 Client.py --id 102 --interval 1.0"
    procs.append(subprocess.Popen(cmd_b, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    
    cmd_c = "python3 Client.py --id 103 --interval 1.0"
    procs.append(subprocess.Popen(cmd_c, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

    # 5. Wait
    for i in range(DURATION, 0, -1):
        sys.stdout.write(f"\r    Running... {i}s remaining ")
        sys.stdout.flush()
        time.sleep(1)
    print("\n    [+] Test Finished.")

    for p in procs: p.terminate()
    server_proc.terminate()
    try: server_proc.wait(timeout=2)
    except: server_proc.kill()
    cleanup()

# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    if os.geteuid() != 0:
        print("[!!!] ERROR: Must run as root (sudo).")
        sys.exit(1)

    if os.path.exists(ROOT_DIR): shutil.rmtree(ROOT_DIR)
    for sec in ["section1_functional", "section2_network", "section3_advanced", "section4_combined"]:
        os.makedirs(f"{ROOT_DIR}/{sec}")

    try:
        # SECTION 1
        print_header("SECTION 1: FUNCTIONAL TESTS")
        sec = "section1_functional"
        run_standard_test(sec, "baseline_1s", 1.0, 1, "none", pcap=True)
        run_standard_test(sec, "batching_mode", 1.0, 5, "none", pcap=True)
        run_standard_test(sec, "fast_rate", 0.05, 1, "none")
        run_standard_test(sec, "forced_heartbeats", 1.0, 1, "none", extra_args="--jam_at 10 --jam_duration 20")

        # SECTION 2
        print_header("SECTION 2: NETWORK IMPAIRMENTS")
        sec = "section2_network"
        run_standard_test(sec, "loss_5_percent", 1.0, 1, "loss 5%", pcap=True)
        run_standard_test(sec, "jitter_reordering", 1.0, 1, "delay 100ms 10ms distribution normal", pcap=True)
        run_standard_test(sec, "duplication_20", 1.0, 1, "duplicate 20%", pcap=True)

        # SECTION 3
        print_header("SECTION 3: SCALABILITY & STRESS")
        sec = "section3_advanced"
        run_standard_test(sec, "multiclient_5_users", 1.0, 1, "none", clients=5)
        run_standard_test(sec, "stress_high_cpu", 0.001, 10, "none") 
        run_intermittent_test(sec)

        # SECTION 4
        print_header("SECTION 4: REAL-WORLD COMPLEXITY")
        sec = "section4_combined"
        
        # Scenario 1: "Bad WiFi"
        run_standard_test(sec, "bad_wifi_simulation", 1.0, 1, "delay 50ms 20ms distribution normal loss 2%", pcap=True)

        # Scenario 2: "Chaos Mode" (Multiple Clients + High Loss)
        # 3 Clients trying to talk over a 5% lossy line
        run_standard_test(sec, "chaos_multi_user_loss", 1.0, 1, "loss 5%", clients=3)

        # Scenario 3: "The Ultimate Test" (Mixed Clients + Mixed Network)
        run_mixed_behavior_test(sec)

    except KeyboardInterrupt:
        print("\n[!] Interrupted.")
    finally:
        cleanup()
        print(f"\n[*] ALL DONE. Results in: {ROOT_DIR}/")