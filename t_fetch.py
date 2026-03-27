import os
import time
from datetime import datetime
import pyvisa
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# config
ADR = "TCPIP0::192.168.30.162::inst0::INSTR"
DIR_OUT = "measurements"
CHANNEL = 1

rm = pyvisa.ResourceManager()


def connect(address: str):
    instr = rm.open_resource(address)
    instr.timeout = 3_000_000  # 50 min timeout
    instr.write_termination = "\n"
    instr.read_termination = "\n"

    idn = instr.query("*IDN?").strip()
    print(idn)
    return instr


def fetch_segments(instr, channel: int = 1):
    print("Stopping acquisition for download...")
    instr.write(":STOP") 
    time.sleep(0.5) # give it time to settle

    instr.write(f":WAVeform:SOURce CHANnel{channel}")
    instr.write(":WAVeform:FORMat BYTE")
    instr.write(":WAVeform:POINts:MODE RAW")

    actual_points = int(instr.query(":WAVeform:POINts?"))
    instr.write(f":WAVeform:POINts {actual_points}")    

    # metadata
    x_inc  = float(instr.query(":WAVeform:XINCrement?"))
    x_orig = float(instr.query(":WAVeform:XORigin?"))
    y_inc  = float(instr.query(":WAVeform:YINCrement?"))
    y_orig = float(instr.query(":WAVeform:YORigin?"))
    y_ref  = float(instr.query(":WAVeform:YREFerence?"))
    
    actual_points = int(instr.query(":WAVeform:POINts?"))
    n_segs = int(instr.query(":ACQuire:SEGMented:COUNt?"))

    print(f"Scope reports {n_segs} segments, {actual_points} points available per segment")
    
    if actual_points == 0:
        err = instr.query(":SYSTem:ERRor?").strip()
        print(f"Scope Error: {err}")


    all_t = []
    all_v = []
    start = time.time()

    for seg in range(1, n_segs + 1):
        instr.write(f":ACQuire:SEGMented:INDex {seg}")
        ttag = float(instr.query(":ACQuire:SEGMented:TTAG?"))

        raw = instr.query_binary_values(
            ":WAVeform:DATA?", datatype="B", container=np.array
        )
        
        if len(raw) == 0:
            print(f"Warning: Segment {seg} returned 0 points")
            continue

        # use actual number of received points for the time array
        t_seg = x_orig + np.arange(len(raw)) * x_inc + ttag

        voltage = (raw - y_ref) * y_inc + y_orig
        all_t.append(t_seg)
        all_v.append(voltage)

    elapsed = time.time() - start
    print(f"Download complete in {elapsed:.2f}s")

    return np.concatenate(all_t), np.concatenate(all_v)


def fetch_single(instr, channel: int = 1):
    instr.write(":STOP")
    instr.write(f":WAVeform:SOURce CHANnel{channel}")

    instr.write(":WAVeform:FORMat WORD") # was byte 256 nivs -> 65536 nivs
    instr.write(":WAVeform:POINts:MODE RAW")
    instr.write(":WAVeform:POINts 15985")

    x_inc  = float(instr.query(":WAVeform:XINCrement?"))
    x_orig = float(instr.query(":WAVeform:XORigin?"))
    y_inc  = float(instr.query(":WAVeform:YINCrement?"))
    y_orig = float(instr.query(":WAVeform:YORigin?"))
    y_ref  = float(instr.query(":WAVeform:YREFerence?"))
    points = int(instr.query(":WAVeform:POINts?"))

    print(f"Waveform: {points} points available")

    raw = instr.query_binary_values(
        ":WAVeform:DATA?", datatype="H", container=np.array # h: signed, H unsinged
    )
    
    if len(raw) == 0:
        err = instr.query(":SYSTem:ERRor?").strip()
        print(f"Scope Error: {err}")
        return np.array([]), np.array([])

    t = x_orig + np.arange(len(raw)) * x_inc
    v = (raw - y_ref) * y_inc + y_orig

    return t, v


def save_csv(t_array, v_array):
    os.makedirs(DIR_OUT, exist_ok=True)
    ts = datetime.now().strftime("%d-%m_%H-%M")
    filename = f"{len(t_array)}P_{ts}.csv"
    filepath = os.path.join(DIR_OUT, filename)

    pd.DataFrame({"t (s)": t_array, "V (V)": v_array}).to_csv(filepath, index=False)
    print(f"Saved: {filepath}")
    return filepath


def plot_data(t_array, v_array):
    plt.figure(figsize=(12, 5))
    plt.plot(t_array * 1e6, v_array, linewidth=0.5)
    plt.xlabel("Time (µs)")
    plt.ylabel("Voltage (V)")
    plt.title(f"Fetched waveform — {len(t_array)} points")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()


def main():
    scope = connect(ADR)
    try:
        mode = scope.query(":ACQuire:MODE?").strip()
        print(f"Acquisition mode: {mode}")

        if "SEGM" in mode.upper():
            t, v = fetch_segments(scope, channel=CHANNEL)
        else:
            t, v = fetch_single(scope, channel=CHANNEL)

        save_csv(t, v)
        plot_data(t, v)

    finally:
        scope.close()
    rm.close()


if __name__ == "__main__":
    main()
