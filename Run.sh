#!/bin/bash

# ============================================================
# IoT Telemetry - Full Automation Suite (Bash Master Version)
# ============================================================
# Usage: sudo ./run_full_suite.sh
# ============================================================

# Configuration
INTERFACE="lo"
ROOT_DIR="experiment_results"
DURATION=40
SERVER_PORT=12000

# 1. Root Check
if [ "$EUID" -ne 0 ]; then
    echo "[!!!] Error: Please run as root (sudo)."
    exit 1
fi

# 2. Cleanup Function
cleanup() {
    # Delete Netem rules (suppress error if none exist)
    tc qdisc del dev $INTERFACE root 2>/dev/null
    
    # Kill background processes
    pkill -f "python3 Server.py"
    pkill -f "python3 Client.py"
    pkill -f "tcpdump"
    
    # Allow sockets to close
    sleep 1
}

# ============================================================
# STANDARD TEST RUNNER
# ============================================================
run_standard_test() {
    SECTION=$1
    NAME=$2
    INTERVAL=$3
    BATCH=$4
    NETEM=$5
    PCAP=$6
    EXTRA_ARGS=$7
    CLIENTS=${8:-1} # Default to 1 client if not specified

    echo ""
    echo "------------------------------------------------------------"
    echo "[*] Scenario: $NAME"
    echo "    Settings: Interval=${INTERVAL}s | Batch=${BATCH} | Clients=${CLIENTS}"
    echo "    Netem: $NETEM"

    CSV_FILE="$ROOT_DIR/$SECTION/$NAME.csv"
    PCAP_FILE="$ROOT_DIR/$SECTION/$NAME.pcap"

    cleanup

    # 1. Apply Network Rules
    if [ "$NETEM" != "none" ]; then
        tc qdisc add dev $INTERFACE root netem $NETEM
    fi

    # 2. Start PCAP
    if [ "$PCAP" -eq 1 ]; then
        tcpdump -i $INTERFACE udp port $SERVER_PORT -w $PCAP_FILE -q > /dev/null 2>&1 &
        sleep 1
    fi

    # 3. Start Server
    # Note: We let server output to stdout so you see the summary at the end
    python3 Server.py --output $CSV_FILE &
    SERVER_PID=$!
    sleep 1

    # 4. Start Clients
    CLIENT_PIDS=()
    for (( i=0; i<CLIENTS; i++ )); do
        ID=$((101 + i))
        python3 Client.py --id $ID --interval $INTERVAL --batch $BATCH $EXTRA_ARGS > /dev/null 2>&1 &
        CLIENT_PIDS+=($!)
        # Small stagger to avoid perfect sync collision at startup
        sleep 0.1
    done

    # 5. Progress Bar
    wait_time=$DURATION
    while [ $wait_time -gt 0 ]; do
        echo -ne "       Running... $wait_time s \r"
        sleep 1
        ((wait_time--))
    done
    echo -e "\n    [+] Test Finished."

    # 6. Teardown - FIXED: Send SIGINT for graceful shutdown
    echo "    [*] Stopping clients..."
    for pid in "${CLIENT_PIDS[@]}"; do
        kill -INT $pid 2>/dev/null
    done
    
    # Wait a moment for clients to stop
    sleep 1
    
    echo "    [*] Stopping server and flushing buffers..."
    # Send SIGINT (same as Ctrl+C) to trigger KeyboardInterrupt
    kill -INT $SERVER_PID 2>/dev/null
    
    # Give the server time to flush buffers (increase if needed)
    sleep 3
    
    # If server is still running, force kill
    if kill -0 $SERVER_PID 2>/dev/null; then
        echo "    [!] Server not responding, force killing..."
        kill -9 $SERVER_PID 2>/dev/null
    fi
    
    wait $SERVER_PID 2>/dev/null
    
    if [ "$NETEM" != "none" ]; then
        tc qdisc del dev $INTERFACE root 2>/dev/null
    fi
    
    echo "    [+] Server stopped and data saved."
}

# ============================================================
# CUSTOM TEST RUNNERS (Tunnel & Mixed)
# ============================================================

run_intermittent_test() {
    SECTION=$1
    NAME="intermittent_tunnel"
    CSV_FILE="$ROOT_DIR/$SECTION/$NAME.csv"

    echo ""
    echo "------------------------------------------------------------"
    echo "[*] Scenario: $NAME (The Tunnel)"
    
    cleanup
    python3 Server.py --output $CSV_FILE &
    SERVER_PID=$!
    sleep 1
    
    python3 Client.py --id 101 --interval 0.5 > /dev/null 2>&1 &
    CLIENT_PID=$!

    echo "    [1/3] Phase Normal (15s)..."
    sleep 15
    
    echo "    [2/3] CUTTING CONNECTION (Loss 100% for 15s)..."
    tc qdisc add dev $INTERFACE root netem loss 100%
    sleep 15
    
    echo "    [3/3] RESTORING CONNECTION (Normal for 15s)..."
    tc qdisc del dev $INTERFACE root
    sleep 15

    echo "    [*] Stopping test..."
    kill -INT $CLIENT_PID 2>/dev/null
    sleep 1
    
    kill -INT $SERVER_PID 2>/dev/null
    sleep 3
    
    if kill -0 $SERVER_PID 2>/dev/null; then
        kill -9 $SERVER_PID 2>/dev/null
    fi
    
    wait $SERVER_PID 2>/dev/null
    cleanup
}

run_mixed_behavior_test() {
    SECTION=$1
    NAME="mixed_clients_complex"
    CSV_FILE="$ROOT_DIR/$SECTION/$NAME.csv"
    PCAP_FILE="$ROOT_DIR/$SECTION/$NAME.pcap"

    echo ""
    echo "------------------------------------------------------------"
    echo "[*] Scenario: $NAME (The Ultimate Test)"
    echo "    Network: Delay 30ms + Jitter 5ms + Loss 2%"
    echo "    Client A: High Load + Jamming"
    echo "    Client B & C: Normal Traffic"

    cleanup
    
    # 1. Global Network Rules
    tc qdisc add dev $INTERFACE root netem delay 30ms 5ms distribution normal loss 2%

    # 2. PCAP
    tcpdump -i $INTERFACE udp port $SERVER_PORT -w $PCAP_FILE -q > /dev/null 2>&1 &
    sleep 1

    # 3. Server
    python3 Server.py --output $CSV_FILE &
    SERVER_PID=$!
    sleep 1

    # 4. Clients
    # Client A: High Load + Jam at 20s
    python3 Client.py --id 101 --interval 0.05 --jam_at 20 --jam_duration 10 > /dev/null 2>&1 &
    PID_A=$!
    
    # Client B: Normal
    python3 Client.py --id 102 --interval 1.0 > /dev/null 2>&1 &
    PID_B=$!

    # Client C: Normal
    python3 Client.py --id 103 --interval 1.0 > /dev/null 2>&1 &
    PID_C=$!

    wait_time=$DURATION
    while [ $wait_time -gt 0 ]; do
        echo -ne "       Running... $wait_time s \r"
        sleep 1
        ((wait_time--))
    done
    echo -e "\n    [+] Test Finished."

    echo "    [*] Stopping clients..."
    kill -INT $PID_A $PID_B $PID_C 2>/dev/null
    sleep 1
    
    echo "    [*] Stopping server and flushing buffers..."
    kill -INT $SERVER_PID 2>/dev/null
    sleep 3
    
    if kill -0 $SERVER_PID 2>/dev/null; then
        kill -9 $SERVER_PID 2>/dev/null
    fi
    
    wait $SERVER_PID 2>/dev/null
    cleanup
}

# ============================================================
# MAIN EXECUTION FLOW
# ============================================================

# Create Directories
if [ -d "$ROOT_DIR" ]; then rm -rf "$ROOT_DIR"; fi
mkdir -p "$ROOT_DIR/section1_functional"
mkdir -p "$ROOT_DIR/section2_network"
mkdir -p "$ROOT_DIR/section3_advanced"
mkdir -p "$ROOT_DIR/section4_combined"

echo ">>> STARTING FULL TEST SUITE <<<"

# --- SECTION 1 ---
echo ">>> SECTION 1: FUNCTIONAL TESTS <<<"
SEC="section1_functional"
# Args: Section, Name, Interval, Batch, Netem, PCAP, ExtraArgs, Clients
run_standard_test $SEC "baseline_1s" 1.0 1 "none" 1 "" 1
run_standard_test $SEC "batching_mode" 1.0 5 "none" 1 "" 1
run_standard_test $SEC "fast_rate" 0.05 1 "none" 0 "" 1
run_standard_test $SEC "forced_heartbeats" 1.0 1 "none" 0 "--jam_at 10 --jam_duration 20" 1

# --- SECTION 2 ---
echo ">>> SECTION 2: NETWORK IMPAIRMENTS <<<"
SEC="section2_network"
run_standard_test $SEC "loss_5_percent" 1.0 1 "loss 5%" 1 "" 1
run_standard_test $SEC "jitter_reordering" 1.0 1 "delay 100ms 10ms distribution normal" 1 "" 1
run_standard_test $SEC "duplication_20" 1.0 1 "duplicate 20%" 1 "" 1

# --- SECTION 3 ---
echo ">>> SECTION 3: SCALABILITY & STRESS <<<"
SEC="section3_advanced"
run_standard_test $SEC "multiclient_5_users" 1.0 1 "none" 0 "" 5
run_standard_test $SEC "stress_high_cpu" 0.001 10 "none" 0 "" 1
run_intermittent_test $SEC

# --- SECTION 4 ---
echo ">>> SECTION 4: REAL-WORLD COMPLEXITY <<<"
SEC="section4_combined"
# Scenario 1: Bad WiFi
run_standard_test $SEC "bad_wifi_simulation" 1.0 1 "delay 50ms 20ms distribution normal loss 2%" 1 "" 1
# Scenario 2: Chaos (3 Clients + Loss)
run_standard_test $SEC "chaos_multi_user_loss" 1.0 1 "loss 5%" 0 "" 3
# Scenario 3: The Ultimate Test
run_mixed_behavior_test $SEC

echo "============================================================"
echo "[*] ALL TESTS COMPLETED."
echo "[*] Results saved in ./$ROOT_DIR"
echo "============================================================"

cleanup