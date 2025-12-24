#!/bin/bash

# ============================================================
# IoT Telemetry - Data Generation Script for Plotting
# ============================================================

INTERFACE="lo"
ROOT_DIR="Output"
DURATION=120  # Required 120s test per scenario
SERVER_PORT=12000

# ----------- Cleanup Function -----------
cleanup() {
    # Remove network impairments
    sudo tc qdisc del dev $INTERFACE root 2>/dev/null
    # Kill background python processes
    pkill -f "python3 Server.py"
    pkill -f "python3 Client.py"
    sleep 1
}

# ----------- Test Execution Function -----------
run_test() {
    NAME=$1
    INTERVAL=$2
    BATCH=$3
    NETEM=$4
    CLIENTS=${5:-1}

    echo "------------------------------------------------------------"
    echo "[*] Running Scenario: $NAME (Interval: ${INTERVAL}s, Netem: $NETEM)"

    # Create directory for the CSV output
    TEST_DIR="$ROOT_DIR/$NAME"
    mkdir -p "$TEST_DIR"
    CSV_FILE="$TEST_DIR/$NAME.csv"

    cleanup

    # Apply network impairment if specified
    if [ "$NETEM" != "none" ]; then
        sudo tc qdisc add dev $INTERFACE root netem $NETEM
    fi

    # Start Server (CSV output directed to scenario folder)
    python3 Server.py --port $SERVER_PORT --output $CSV_FILE &
    SERVER_PID=$!
    sleep 2

    # Start Client(s)
    CLIENT_PIDS=()
    for (( i=0; i<CLIENTS; i++ )); do
        ID=$((101 + i))
        python3 Client.py --id $ID --host "localhost" --port $SERVER_PORT --interval $INTERVAL --batch $BATCH > /dev/null 2>&1 &
        CLIENT_PIDS+=($!)
        sleep 0.1
    done

    # Run for the specified duration
    sleep $DURATION

    # Graceful Shutdown
    for pid in "${CLIENT_PIDS[@]}"; do kill -INT $pid 2>/dev/null; done
    sleep 1
    kill -INT $SERVER_PID 2>/dev/null
    sleep 2
    
    # Force kill if still hanging
    kill -9 $SERVER_PID 2>/dev/null
    sudo tc qdisc del dev $INTERFACE root 2>/dev/null
}

# ----------- Main Execution -----------
mkdir -p "$ROOT_DIR"
trap cleanup EXIT

echo "[*] Starting Data Collection..."

# 1. Baseline & CPU Load Series (Required for Plot A and Plot C)
run_test "baseline_0.5s" 0.5 1 "none"
run_test "baseline_1s"   1.0 1 "none"
run_test "baseline_5s"   5.0 1 "none"
run_test "baseline_10s"  10.0 1 "none"
run_test "baseline_20s"  20.0 1 "none"
run_test "baseline_30s"  30.0 1 "none"

# 2. Robustness/Loss Series (Required for Plot B)
# Note: baseline_1s (0% loss) is already generated above
run_test "loss_5_percent"  1.0 1 "loss 5%"
run_test "loss_10_percent" 1.0 1 "loss 10%"
run_test "loss_20_percent" 1.0 1 "loss 20%"
run_test "loss_30_percent" 1.0 1 "loss 30%"

# 3. Jitter Series (Required for Plot D)
run_test "jitter_test" 1.0 1 "delay 100ms 10ms distribution normal"

echo "------------------------------------------------------------"
echo "[*] All data generated in '$ROOT_DIR' folder."

# This is the line to add:
python3 plot_results.py

echo "[*] Graphs have been generated in the 'Graphs' folder."

cleanup
echo "[*] Done."

cleanup