import pandas as pd
import matplotlib.pyplot as plt
import sys
import os

def generate_plots(csv_file):
    try:
        # Load Data
        df = pd.read_csv(csv_file)
        
        if df.empty:
            print(f"[!] Warning: {csv_file} is empty. Skipping.")
            return

        # Create Output Filename (same folder as CSV)
        base_name = os.path.splitext(csv_file)[0]
        output_file = f"{base_name}_analysis.png"
        
        # Setup Figure (3 subplots)
        fig, ax = plt.subplots(3, 1, figsize=(10, 12), sharex=True)
        fig.suptitle(f'Protocol Analysis: {os.path.basename(csv_file)}', fontsize=16)

        # Calculate relative time (start at 0)
        # Handle case where file might have only 1 row or messy timestamps
        start_time = df['arrival_time'].min()
        relative_time = df['arrival_time'] - start_time
        
        # --- Plot 1: Latency & Jitter ---
        # Filter out negative latency (clock sync issues) for cleaner graphs
        valid_mask = df['latency_ms'] >= 0
        valid_latency = df.loc[valid_mask, 'latency_ms']
        valid_time = relative_time[valid_mask]
        
        ax[0].plot(valid_time, valid_latency, label='Latency', color='blue', alpha=0.7)
        ax[0].plot(relative_time, df['jitter_ms'], label='Jitter', color='orange', alpha=0.5)
        ax[0].set_ylabel('Time (ms)')
        ax[0].set_title('Network Performance')
        ax[0].legend(loc='upper right')
        ax[0].grid(True)

        # --- Plot 2: Sequence Gaps (Loss) & Duplicates ---
        # Gaps
        gaps = df[df['gap_flag'] == 1]
        if not gaps.empty:
            gap_times = gaps['arrival_time'] - start_time
            ax[1].bar(gap_times, gaps['gap_count'], width=0.5, color='red', label='Packets Lost (Gap)')
        
        # Duplicates
        dups = df[df['duplicate_flag'] == 1]
        if not dups.empty:
             dup_times = dups['arrival_time'] - start_time
             # Plot duplicates as 'X' slightly above 0 so they are visible
             ax[1].scatter(dup_times, [1]*len(dups), color='purple', marker='x', label='Duplicate Detected')

        ax[1].set_ylabel('Count / Events')
        ax[1].set_title('Reliability (Loss & Duplicates)')
        ax[1].legend(loc='upper right')
        ax[1].grid(True)
        # Force Y-axis to be integers if counts are low
        ax[1].yaxis.get_major_locator().set_params(integer=True)


        # --- Plot 3: Message Types & Throughput ---
        # Visualize when Data vs Heartbeats arrived
        data_msgs = df[df['msg_type'] == 1]
        hb_msgs = df[df['msg_type'] == 2]
        
        # We plot these on specific Y-levels to separate them visually
        if not data_msgs.empty:
            ax[2].scatter(data_msgs['arrival_time'] - start_time, [1]*len(data_msgs), 
                          color='green', label='Data Packet', s=15, alpha=0.6)
        if not hb_msgs.empty:
            ax[2].scatter(hb_msgs['arrival_time'] - start_time, [2]*len(hb_msgs), 
                          color='magenta', marker='^', label='Heartbeat', s=40)
            
        ax[2].set_yticks([1, 2])
        ax[2].set_yticklabels(['Data', 'Heartbeat'])
        ax[2].set_xlabel('Experiment Duration (Seconds)')
        ax[2].set_title('Traffic Pattern')
        ax[2].legend(loc='center right')
        ax[2].grid(True, axis='x')
        
        # Adjust layout to prevent overlap
        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        
        # Save
        plt.savefig(output_file)
        print(f"[+] Plot generated: {output_file}")
        plt.close()

    except Exception as e:
        print(f"[!] Error plotting {csv_file}: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 plot_results.py <folder_path>")
        print("Example: python3 plot_results.py experiment_results")
        sys.exit(1)

    target_dir = sys.argv[1]
    
    if not os.path.exists(target_dir):
        print(f"[!] Error: Directory '{target_dir}' not found.")
        sys.exit(1)

    print(f"[*] Scanning directory: {target_dir} ...")
    
    # Walk through directory and find all CSVs
    count = 0
    for root, dirs, files in os.walk(target_dir):
        for file in files:
            if file.endswith(".csv"):
                full_path = os.path.join(root, file)
                generate_plots(full_path)
                count += 1
    
    if count == 0:
        print("[!] No CSV files found.")
    else:
        print(f"[*] Done. Generated {count} plots.")