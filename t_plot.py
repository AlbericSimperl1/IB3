import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

import sys
import os

def plot_csv(filepath):
    if not os.path.exists(filepath):
        print(f"Bestand niet gevonden: {filepath}")
        sys.exit(1)

    df = pd.read_csv(filepath)

    x_col = df.columns[0]
    y_col = df.columns[1]

    plt.figure(figsize=(12, 5))
    plt.plot(df[x_col] * 1e6, df[y_col], linewidth=0.5)

    plt.xlabel("Time (µs)")
    plt.ylabel("Voltage (V)")
    plt.title(f"{os.path.basename(filepath)} — {len(df)} points")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(1)

    plot_csv(sys.argv[1])