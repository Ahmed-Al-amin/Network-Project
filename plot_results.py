import pandas as pd
import matplotlib.pyplot as plt
import os

OUTPUT_DIR = "Output"
GRAPHS_DIR = "Graphs"
HEADER_SIZE = 11  # 9B Header + 2B Checksum

if not os.path.exists(GRAPHS_DIR):
    os.makedirs(GRAPHS_DIR)

def load_csv(test_name):
    path = os.path.join(OUTPUT_DIR, test_name, f"{test_name}.csv")
    if not os.path.exists(path):
        print(f"[!] Missing: {path}")
        return None
    return pd.read_csv(path)

# ==========================================
# PLOT A: Bytes vs Interval
# ==========================================
def plot_a_overhead():
    print("[*] Generating Plot A: Overhead...")
    scenarios = [("1s", "baseline_1s"), ("5s", "baseline_5s"), 
                 ("10s", "baseline_10s"), ("20s", "baseline_20s"), ("30s", "baseline_30s")]
    
    x, y = [], []
    for lbl, folder in scenarios:
        df = load_csv(folder)
        if df is not None:
            x.append(lbl)
            y.append(df['payload_size'].mean() + HEADER_SIZE)

    if not x: return

    plt.figure(figsize=(8, 5))
    bars = plt.bar(x, y, color='#2ecc71', edgecolor='black', alpha=0.8)
    plt.title('Protocol Overhead: Avg Bytes per Report vs Interval')
    plt.xlabel('Reporting Interval')
    plt.ylabel('Avg Packet Size (Bytes)')
    plt.ylim(0, 35)
    plt.grid(axis='y', linestyle='--', alpha=0.5)
    
    for bar in bars:
        plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5, 
                 f"{bar.get_height():.1f} B", ha='center', fontweight='bold')
    
    plt.savefig(f"{GRAPHS_DIR}/plot_a_overhead.png", dpi=300)
    plt.close()

# ==========================================
# PLOT B: Gap Detection vs Loss
# ==========================================
def plot_b_robustness():
    print("[*] Generating Plot B: Robustness (Gaps)...")
    scenarios = [(0, "baseline_1s"), (5, "loss_5_percent"),
                 (10, "loss_10_percent"), (20, "loss_20_percent"), (30, "loss_30_percent")]
    
    x, y = [], []
    for loss, folder in scenarios:
        df = load_csv(folder)
        if df is not None:
            x.append(loss)
            y.append(df['gap_count'].sum())

    if not x: return

    plt.figure(figsize=(8, 5))
    plt.plot(x, y, marker='o', color='#e74c3c', linewidth=2, markersize=8)
    plt.title('Robustness: Gap Detection vs Packet Loss')
    plt.xlabel('Simulated Loss (%)')
    plt.ylabel('Total Gaps Detected')
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.xticks([0, 5, 10, 15, 20, 25, 30])
    
    for i, txt in enumerate(y):
        plt.annotate(f"{txt}", (x[i], y[i]), xytext=(0, 10), textcoords='offset points', ha='center')

    plt.savefig(f"{GRAPHS_DIR}/plot_b_robustness.png", dpi=300)
    plt.close()

# ==========================================
# PLOT C: CPU Cost
# ==========================================
def plot_c_cpu():
    print("[*] Generating Plot C: CPU Cost...")
    scenarios = [("Very High (0.5s)", "baseline_0.5s"), ("High (1s)", "baseline_1s"),
                 ("Medium (10s)", "baseline_10s"), ("Low (30s)", "baseline_30s")]
    
    x, y = [], []
    for lbl, folder in scenarios:
        df = load_csv(folder)
        if df is not None:
            x.append(lbl)
            y.append(df['cpu_ms'].mean() * 1000) # Convert to microseconds

    if not x: return

    plt.figure(figsize=(8, 5))
    bars = plt.bar(x, y, color='#9b59b6', edgecolor='black', width=0.5, alpha=0.8)
    plt.title('Server Performance: CPU Cost per Packet')
    plt.ylabel('Processing Time (microseconds)')
    plt.grid(axis='y', linestyle='--', alpha=0.5)
    
    for bar in bars:
        plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1, 
                 f"{bar.get_height():.1f} µs", ha='center', fontweight='bold')

    plt.savefig(f"{GRAPHS_DIR}/plot_c_cpu.png", dpi=300)
    plt.close()

# ==========================================
# PLOT D: Latency Distribution (Jitter)
# ==========================================
def plot_d_jitter():
    print("[*] Generating Plot D: Latency Distribution...")
    scenarios = [("Stable (Baseline)", "baseline_1s"), ("Unstable (Jitter)", "jitter_test")]
    
    data = []
    labels = []
    
    for lbl, folder in scenarios:
        df = load_csv(folder)
        if df is not None:
            data.append(df['latency_ms'])
            labels.append(lbl)

    if not data: return

    plt.figure(figsize=(6, 5))
    plt.boxplot(data, labels=labels, patch_artist=True, 
                boxprops=dict(facecolor='#3498db', color='black'),
                medianprops=dict(color='red'))
    plt.title('Jitter Analysis: End-to-End Latency Distribution')
    plt.ylabel('Latency (ms)')
    plt.grid(axis='y', linestyle='--', alpha=0.5)

    plt.savefig(f"{GRAPHS_DIR}/plot_d_jitter.png", dpi=300)
    plt.close()
# ==========================================


if __name__ == "__main__":
    plot_a_overhead()
    plot_b_robustness()
    plot_c_cpu()
    plot_d_jitter()
    print("[*] Done! Check the 'Graphs' folder.")