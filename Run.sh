#!/bin/bash

# ============================================================
# IoT Telemetry - Functional Tests
# ============================================================

INTERFACE="lo"
ROOT_DIR="Output"
DURATION=60
SERVER_PORT=12000

# ----------- Common Cleanup Function -----------
cleanup() {
    tc qdisc del dev $INTERFACE root 2>/dev/null
    pkill -f "python3 Server.py"
    pkill -f "python3 Client.py"
    pkill -f "tcpdump"
    sleep 1
}

# ----------- Core Test Function -----------
run_test() {
    NAME=$1
    INTERVAL=$2
    BATCH=$3
    NETEM=$4
    EXTRA_ARGS=$5
    CLIENTS=${6:-1}

    echo "------------------------------------------------------------"
    echo "[*] Scenario: $NAME"

    # --- Create Folder per Test Case ---
    TEST_DIR="$ROOT_DIR/$NAME"
    mkdir -p "$TEST_DIR"

    CSV_FILE="$TEST_DIR/$NAME.csv"
    PCAP_FILE="$TEST_DIR/$NAME.pcap"
    # -----------------------------------

    cleanup

    if [ "$NETEM" != "none" ]; then
        tc qdisc add dev $INTERFACE root netem $NETEM
    fi

    # --- Always Record PCAP ---
    tcpdump -i $INTERFACE udp port $SERVER_PORT -w $PCAP_FILE -q > /dev/null 2>&1 &
    sleep 1
    # --------------------------

    python3 Server.py --port $SERVER_PORT --output $CSV_FILE &
    SERVER_PID=$!
    sleep 1

    CLIENT_PIDS=()
    for (( i=0; i<CLIENTS; i++ )); do
        ID=$((101 + i))
        python3 Client.py --id $ID --host "localhost" --port $SERVER_PORT --interval $INTERVAL --batch $BATCH $EXTRA_ARGS > /dev/null 2>&1 &
        CLIENT_PIDS+=($!)
        sleep 0.1
    done

    sleep $DURATION
    echo ""

    for pid in "${CLIENT_PIDS[@]}"; do kill -INT $pid; done
    sleep 1

    kill -INT $SERVER_PID
    sleep 3
    kill -9 $SERVER_PID 2>/dev/null
    
    tc qdisc del dev $INTERFACE root 2>/dev/null
    

}

# ----------- Create Root Directory -----------
mkdir -p "$ROOT_DIR"

# ----------- Run Tests -----------

# 1. Baseline
run_test "baseline_1s" 1.0 1 "none" ""

# 2. Batching
run_test "batching_mode" 1.0 5 "none" ""

# 3. Heartbeat
run_test "test_heartbeat" 25.0 1 "none" "" 

# 4. Loss 5%
run_test "loss_5_percent" 1.0 1 "loss 5%"

# 5. Jitter
run_test "jitter_reordering" 1.0 1 "delay 100ms 10ms distribution normal"

# 6. Duplication
run_test "duplication_20" 1.0 1 "duplicate 20%"

# 7. Multi-Client (3 Users)
run_test "multiclient_3_users" 1.0 1 "none" "" 3

# 8. Loss 30%
run_test "Loss_30_percent" 1.0 1 "loss 30%"

cleanup
echo "[*] All Tests Completed."

