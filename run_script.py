import subprocess
import time
import os
import signal

print("--- Starting Phase 1 Baseline Test (Python Script) ---")
print("This test will run for 20 seconds...")
print("")

print("Starting Collector (Server)...")
server_process = subprocess.Popen(['python', 'Server.py'])
print(f"Server started with PID: {server_process.pid}")

time.sleep(2)

print("Starting Sensor (Client)...")
client_process = subprocess.Popen(['python', 'Client.py'])
print(f"Client started with PID: {client_process.pid}")

print("")
print("Test is running. Waiting for 20 seconds...")
time.sleep(65)
print("Test duration complete.")
print("")

print(f"Stopping Sensor (Client) with PID: {client_process.pid}")
client_process.terminate() 


print(f"Stopping Collector (Server) with PID: {server_process.pid}")
server_process.terminate() 

print("")
print("--- Test Finished ---")
print("Please check the 'telemetry_log.csv' file for results.")