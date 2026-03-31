import os
import time
import numpy as np
import pandas as pd
import pyvisa
from datetime import datetime

# CONFIGURATIE
ADR = "TCPIP0::192.168.30.162::inst0::INSTR"
DIR_OUT = "measurements_high_speed"
CHANNEL = 1
MAX_SEGMENTS = 1000  # Maximaal aantal segmenten dat de scope aankan (check manual)
TIMEOUT_MS = 60000   # 60 seconden timeout voor transfer

def connect_robust(address: str):
    """Verbinding maken met strenge timeouts en error checking."""
    rm = pyvisa.ResourceManager()
    instr = rm.open_resource(address)
    instr.timeout = TIMEOUT_MS
    instr.write_termination = "\n"
    instr.read_termination = "\n"
    
    # Reset de scope naar een bekende staat
    instr.write("*RST")
    time.sleep(1)
    instr.write("*CLS") # Clear status registers
    
    idn = instr.query("*IDN?").strip()
    print(f"Connected to: {idn}")
    return instr, rm

def setup_sequence_mode(instr, channel: int, n_segments: int, sample_rate_target: float):
    """
    Configureert de scope voor Sequence Mode (Segmented Memory).
    Dit minimaliseert dead time tot het hardware minimum (vaak < 1µs).
    """
    print(f"Configuring Sequence Mode for {n_segments} segments...")
    
    # 1. Stop alles en reset acquisitie
    instr.write(":STOP")
    instr.write(":ACQuire:MODE SEGMented")
    instr.write(f":ACQuire:SEGMented:COUNt {n_segments}")
    
    # 2. Trigger instellen (Cruciaal voor 1GHz signaal!)
    # We triggeren op het signaal zelf zodat we alleen relevante data capturen
    instr.write(f":TRIGger:SOURce CHANnel{channel}")
    instr.write(":TRIGger:TYPE EDGE")
    instr.write(f":TRIGger:EDGE:SOURce CHANnel{channel}")
    instr.write(":TRIGger:EDGE:SLOpe POSitive")
    # Trigger level op 50% van het scherm zetten (moet misschien dynamisch)
    instr.write(":TRIGger:LEVEL 0.0") 
    
    # 3. Waveform setup
    instr.write(f":WAVeform:SOURce CHANnel{channel}")
    instr.write(":WAVeform:FORMat BYTE") # Snelste formaat
    instr.write(":WAVeform:BYTeorder LSBF")
    instr.write(":WAVeform:POINts:MODE RAW")
    
    # Vraag maximale punten per segment op die de scope aankan bij deze mode
    max_pts = int(instr.query(":WAVeform:POINts:MAXimum?"))
    # Gebruik bijvoorbeeld 10k punten per segment voor snelheid vs resolutie trade-off
    points_per_seg = min(10000, max_pts) 
    instr.write(f":WAVeform:POINts {points_per_seg}")
    
    # 4. Tijdsbasis instellen (Belangrijk voor 1GHz)
    # Voor 1GHz heb je minimaal 2.5 GSa/s nodig (Nyquist), liever 5-10 GSa/s.
    # Stel tijdsbasis in op bijv. 2ns/div om meerdere cycli te zien
    instr.write(":TIMebase:SCALe 2e-9") 
    
    # Check daadwerkelijke sample rate
    rate = float(instr.query(":ACQuire:SRATe?"))
    print(f"Acquisition Sample Rate: {rate/1e9:.2f} GSa/s")
    
    if rate < 2.5e9:
        print("WAARSCHUWING: Sample rate is te laag voor een 1GHz signaal (Nyquist)!")
    
    return points_per_seg, rate

def acquire_sequence(instr, n_segments: int):
    """
    Voert de acquisitie uit en haalt alle data in één bulk op.
    """
    print("Arming sequence acquisition...")
    instr.write(":RUN")
    
    # Wachten tot alle segmenten gevuld zijn
    # We pollen de 'ACQuire:STATE' of wachten op een event
    start_wait = time.time()
    while True:
        state = instr.query(":ACQuire:STATE?").strip()
        if state == "0": # 0 = Idle/Stopped (klaar)
            break
        if time.time() - start_wait > 30: # Timeout na 30s
            raise TimeoutError("Acquisitie duurde te lang. Trigger misschien niet geraakt?")
        time.sleep(0.1)
        
    print("Acquisition complete. Starting download...")
    
    # Metadata ophalen (eenmalig)
    x_inc = float(instr.query(":WAVeform:XINCrement?"))
    x_orig_base = float(instr.query(":WAVeform:XORigin?"))
    y_inc = float(instr.query(":WAVeform:YINCrement?"))
    y_orig = float(instr.query(":WAVeform:YORigin?"))
    y_ref = float(instr.query(":WAVeform:YREFerence?"))
    
    all_t = []
    all_v = []
    all_tags = []
    
    start_dl = time.time()
    
    # Optimatie: Sommige scopes ondersteunen ":WAVeform:DATA? START, COUNT" voor bulk
    # Maar voor segmented moeten we vaak per segment loopen, tenzij de scope 'Streaming' support heeft.
    # Hier loopen we efficient door de segmenten.
    
    for seg in range(1, n_segments + 1):
        instr.write(f":ACQuire:SEGMented:INDex {seg}")
        
        # Haal de relatieve timestamp van dit segment op
        t_tag = float(instr.query(":ACQuire:SEGMented:TTAG?"))
        
        # Haal data op (Binary is veel sneller dan ASCII)
        raw = instr.query_binary_values(":WAVeform:DATA?", datatype="B", container=np.array)
        
        if len(raw) == 0:
            continue
            
        # Conversie naar Voltage
        voltage = (raw.astype(np.float32) - y_ref) * y_inc + y_orig
        
        # Tijd berekening: Base Origin + (Sample Index * Increment) + Segment Offset (TTAG)
        # TTAG is meestal de tijd vanaf trigger tot start van dit segment
        t_seg = x_orig_base + (np.arange(len(raw)) * x_inc) + t_tag
        
        all_t.append(t_seg)
        all_v.append(voltage)
        all_tags.append(t_tag)
        
        if seg % 100 == 0:
            print(f"Downloaded {seg}/{n_segments} segments...")
            
    elapsed = time.time() - start_dl
    print(f"Download finished in {elapsed:.2f}s ({n_segments/elapsed:.1f} segments/sec)")
    
    # Concateneren
    final_t = np.concatenate(all_t)
    final_v = np.concatenate(all_v)
    
    return final_t, final_v, np.array(all_tags)

def analyze_gaps(t_tags, sample_rate):
    """Analyseert de dead time tussen segmenten."""
    if len(t_tags) < 2:
        return
        
    diffs = np.diff(t_tags)
    # Verwachte tijd tussen segmenten = aantal punten * x_inc
    # Als diffs groter zijn dan de duur van een segment, hebben we dead time
    
    avg_gap = np.mean(diffs)
    min_gap = np.min(diffs)
    
    print(f"\n--- Timing Analyse ---")
    print(f"Aantal segmenten: {len(t_tags)}")
    print(f"Gemiddelde tijd tussen segment starts: {avg_gap*1e9:.2f} ns")
    print(f"Minimale tijd tussen segment starts: {min_gap*1e9:.2f} ns")
    print("Let op: Dead time = (Tijd tussen starts) - (Duur van 1 segment)")

def save_results(t, v, tags):
    os.makedirs(DIR_OUT, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"seq_{len(t)}pts_{ts}.csv"
    filepath = os.path.join(DIR_OUT, filename)
    
    # Opslaan met metadata
    df = pd.DataFrame({"time_s": t, "voltage_V": v})
    df.to_csv(filepath, index=False)
    print(f"Data saved to: {filepath}")

def main():
    instr, rm = connect_robust(ADR)
    
    try:
        # 1. Setup
        # We vragen de scope hoeveel segmenten hij maximaal ondersteunt
        max_supported = int(instr.query(":ACQuire:SEGMented:COUNt:MAXimum?"))
        n_segs = min(MAX_SEGMENTS, max_supported)
        
        pts, rate = setup_sequence_mode(instr, CHANNEL, n_segs, sample_rate_target=5e9)
        
        # 2. Acquire
        t, v, tags = acquire_sequence(instr, n_segs)
        
        if len(t) == 0:
            print("Geen data ontvangen. Check trigger instellingen.")
            return

        # 3. Analyse
        analyze_gaps(tags, rate)
        
        # 4. Opslaan
        save_results(t, v, tags)
        
        # Optioneel: Plot eerste 5 segmenten ter verificatie
        import matplotlib.pyplot as plt
        plt.figure(figsize=(12, 6))
        plot_limit = min(len(t), 50000) # Plot niet alles als het te groot is
        plt.plot(t[:plot_limit]*1e9, v[:plot_limit], lw=0.5)
        plt.xlabel("Time (ns)")
        plt.ylabel("Voltage (V)")
        plt.title(f"First {plot_limit} samples @ {rate/1e9} GSa/s")
        plt.grid(True, alpha=0.3)
        plt.show()

    except Exception as e:
        print(f"Fout opgetreden: {e}")
    finally:
        instr.write(":STOP")
        instr.close()
        rm.close()

if __name__ == "__main__":
    main()