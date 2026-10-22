"""Generate a SYNTHETIC, CICIDS2017-shaped CSV for smoke-testing the pipeline.

This is NOT real network traffic and NOT the CICIDS2017 dataset. Class-conditional distributions
are invented, so any model trained on it demonstrates that the software works end to end and
nothing about real-world detection quality. Models trained from this file are flagged as synthetic
in their metadata and the dashboard shows a banner.

For real results, download CICIDS2017 (MachineLearningCVE CSVs) from
https://www.unb.ca/cic/datasets/ids-2017.html and train on that instead.

Usage:
    python scripts/generate_synthetic_data.py --out ../data/synthetic/synthetic_cicids_like.csv --rows 30000
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

FEATURES = [
    "Destination Port", "Flow Duration", "Total Fwd Packets", "Total Backward Packets",
    "Total Length of Fwd Packets", "Total Length of Bwd Packets", "Fwd Packet Length Max",
    "Fwd Packet Length Min", "Fwd Packet Length Mean", "Fwd Packet Length Std", "Bwd Packet Length Max",
    "Bwd Packet Length Min", "Bwd Packet Length Mean", "Bwd Packet Length Std", "Flow Bytes/s",
    "Flow Packets/s", "Flow IAT Mean", "Flow IAT Std", "Flow IAT Max", "Flow IAT Min", "Fwd IAT Total",
    "Fwd IAT Mean", "Fwd IAT Std", "Fwd IAT Max", "Fwd IAT Min", "Bwd IAT Total", "Bwd IAT Mean",
    "Bwd IAT Std", "Bwd IAT Max", "Bwd IAT Min", "Fwd PSH Flags", "Bwd PSH Flags", "Fwd URG Flags",
    "Bwd URG Flags", "Fwd Header Length", "Bwd Header Length", "Fwd Packets/s", "Bwd Packets/s",
    "Min Packet Length", "Max Packet Length", "Packet Length Mean", "Packet Length Std",
    "Packet Length Variance", "FIN Flag Count", "SYN Flag Count", "RST Flag Count", "PSH Flag Count",
    "ACK Flag Count", "URG Flag Count", "CWE Flag Count", "ECE Flag Count", "Down/Up Ratio",
    "Average Packet Size", "Avg Fwd Segment Size", "Avg Bwd Segment Size", "Fwd Header Length.1",
    "Fwd Avg Bytes/Bulk", "Fwd Avg Packets/Bulk", "Fwd Avg Bulk Rate", "Bwd Avg Bytes/Bulk",
    "Bwd Avg Packets/Bulk", "Bwd Avg Bulk Rate", "Subflow Fwd Packets", "Subflow Fwd Bytes",
    "Subflow Bwd Packets", "Subflow Bwd Bytes", "Init_Win_bytes_forward", "Init_Win_bytes_backward",
    "act_data_pkt_fwd", "min_seg_size_forward", "Active Mean", "Active Std", "Active Max", "Active Min",
    "Idle Mean", "Idle Std", "Idle Max", "Idle Min",
]

# Invented per-class profiles: (log10 duration us, fwd pkts, bwd pkts, mean fwd len, mean bwd len,
# destination ports, SYN prob, RST prob, relative weight)
PROFILES = {
    "BENIGN":                      (5.5, 8, 7, 120, 350, [80, 443, 53, 8080, 22, 3389], 0.10, 0.02, 0.62),
    "DDoS":                        (4.9, 4, 0, 20, 0, [80], 0.30, 0.02, 0.10),
    "DoS Hulk":                    (6.4, 5, 3, 300, 40, [80], 0.20, 0.02, 0.10),
    "PortScan":                    (2.5, 1, 1, 0, 0, list(range(1, 1024)), 0.05, 0.90, 0.07),
    "FTP-Patator":                 (5.2, 9, 8, 15, 30, [21], 0.12, 0.02, 0.03),
    "SSH-Patator":                 (6.0, 20, 24, 60, 60, [22], 0.10, 0.02, 0.03),
    "Bot":                         (6.2, 6, 5, 70, 50, [8080, 443], 0.10, 0.02, 0.02),
    "Web Attack - Brute Force":    (6.1, 12, 10, 350, 600, [80], 0.10, 0.02, 0.015),
    "Web Attack - XSS":            (6.2, 11, 9, 330, 580, [80], 0.10, 0.02, 0.010),
    "Infiltration":                (7.0, 40, 38, 500, 800, [444, 8080], 0.10, 0.02, 0.003),
    "Heartbleed":                  (8.2, 250, 600, 200, 4000, [444], 0.05, 0.01, 0.0015),
}


def generate(rows: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    names = list(PROFILES)
    weights = np.array([PROFILES[n][-1] for n in names])
    weights = weights / weights.sum()
    labels = rng.choice(names, size=rows, p=weights)
    # make sure every class has a few rows even for tiny --rows values
    for i, name in enumerate(names):
        labels[i] = name
    records = []
    for label in labels:
        ldur, fwd, bwd, flen, blen, ports, syn, rst, _ = PROFILES[label]
        noise = lambda s=0.35: float(rng.lognormal(0, s))  # noqa: E731
        duration = max(1.0, 10 ** (ldur + rng.normal(0, 0.45)))
        n_fwd = max(1, int(round(fwd * noise())))
        n_bwd = max(0, int(round(bwd * noise()))) if bwd else 0
        mean_fwd = max(0.0, flen * noise(0.25))
        mean_bwd = max(0.0, blen * noise(0.25)) if n_bwd else 0.0
        tot_fwd = mean_fwd * n_fwd
        tot_bwd = mean_bwd * n_bwd
        pkts = n_fwd + n_bwd
        dur_s = duration / 1e6
        iat_mean = duration / max(pkts - 1, 1)
        row = dict.fromkeys(FEATURES, 0.0)
        row.update({
            "Destination Port": int(rng.choice(ports)),
            "Flow Duration": duration,
            "Total Fwd Packets": n_fwd, "Total Backward Packets": n_bwd,
            "Total Length of Fwd Packets": tot_fwd, "Total Length of Bwd Packets": tot_bwd,
            "Fwd Packet Length Max": mean_fwd * 1.8, "Fwd Packet Length Min": mean_fwd * 0.2,
            "Fwd Packet Length Mean": mean_fwd, "Fwd Packet Length Std": mean_fwd * 0.5,
            "Bwd Packet Length Max": mean_bwd * 1.8, "Bwd Packet Length Min": mean_bwd * 0.2,
            "Bwd Packet Length Mean": mean_bwd, "Bwd Packet Length Std": mean_bwd * 0.5,
            "Flow Bytes/s": (tot_fwd + tot_bwd) / dur_s, "Flow Packets/s": pkts / dur_s,
            "Flow IAT Mean": iat_mean, "Flow IAT Std": iat_mean * 0.8 * noise(), "Flow IAT Max": iat_mean * 3 * noise(),
            "Flow IAT Min": iat_mean * 0.1 * noise(), "Fwd IAT Total": duration * 0.95,
            "Fwd IAT Mean": duration / max(n_fwd, 1), "Fwd IAT Std": iat_mean * noise(), "Fwd IAT Max": iat_mean * 3 * noise(),
            "Fwd IAT Min": iat_mean * 0.1 * noise(), "Bwd IAT Total": duration * 0.9 if n_bwd else 0.0,
            "Bwd IAT Mean": duration / max(n_bwd, 1) if n_bwd else 0.0, "Bwd IAT Std": iat_mean * noise() if n_bwd else 0.0,
            "Bwd IAT Max": iat_mean * 3 * noise() if n_bwd else 0.0, "Bwd IAT Min": iat_mean * 0.1 * noise() if n_bwd else 0.0,
            "Fwd PSH Flags": 0, "Bwd PSH Flags": 0, "Fwd URG Flags": 0, "Bwd URG Flags": 0,
            "Fwd Header Length": n_fwd * 20, "Bwd Header Length": n_bwd * 20,
            "Fwd Packets/s": n_fwd / dur_s, "Bwd Packets/s": n_bwd / dur_s,
            "Min Packet Length": min(mean_fwd, mean_bwd) * 0.2 if n_bwd else mean_fwd * 0.2,
            "Max Packet Length": max(mean_fwd, mean_bwd) * 1.8,
            "Packet Length Mean": (tot_fwd + tot_bwd) / pkts, "Packet Length Std": (mean_fwd + mean_bwd) * 0.4,
            "Packet Length Variance": ((mean_fwd + mean_bwd) * 0.4) ** 2,
            "FIN Flag Count": int(rng.random() < 0.4), "SYN Flag Count": int(rng.random() < syn),
            "RST Flag Count": int(rng.random() < rst), "PSH Flag Count": int(rng.random() < 0.4),
            "ACK Flag Count": int(rng.random() < 0.6), "URG Flag Count": int(rng.random() < 0.05),
            "CWE Flag Count": 0, "ECE Flag Count": 0,
            "Down/Up Ratio": int(n_bwd / max(n_fwd, 1)),
            "Average Packet Size": (tot_fwd + tot_bwd) / pkts * 1.05,
            "Avg Fwd Segment Size": mean_fwd, "Avg Bwd Segment Size": mean_bwd,
            "Fwd Header Length.1": n_fwd * 20,
            "Subflow Fwd Packets": n_fwd, "Subflow Fwd Bytes": tot_fwd,
            "Subflow Bwd Packets": n_bwd, "Subflow Bwd Bytes": tot_bwd,
            "Init_Win_bytes_forward": int(rng.choice([-1, 229, 8192, 29200, 65535])),
            "Init_Win_bytes_backward": int(rng.choice([-1, 235, 8192, 28960, 65535])) if n_bwd else -1,
            "act_data_pkt_fwd": max(0, n_fwd - 1), "min_seg_size_forward": int(rng.choice([20, 32, 40])),
            "Active Mean": duration * 0.1 * noise(), "Active Std": duration * 0.02 * noise(),
            "Active Max": duration * 0.2 * noise(), "Active Min": duration * 0.05 * noise(),
            "Idle Mean": duration * 0.5 * noise() if duration > 1e6 else 0.0, "Idle Std": 0.0,
            "Idle Max": duration * 0.6 * noise() if duration > 1e6 else 0.0,
            "Idle Min": duration * 0.4 * noise() if duration > 1e6 else 0.0,
        })
        row["Label"] = label
        records.append(row)

    df = pd.DataFrame.from_records(records)

    # Context columns in the style of the "GeneratedLabelledFlows" CICIDS2017 CSVs.
    n = len(df)
    base = pd.Timestamp("2017-07-05 09:00:00")
    minutes = rng.integers(0, 8 * 60, size=n)
    stamps = base + pd.to_timedelta(minutes, unit="m")
    df.insert(0, "Timestamp", [f"{t.month}/{t.day}/{t.year} {t.hour}:{t.minute:02d}" for t in stamps])
    src = [f"192.168.10.{int(x)}" for x in rng.integers(2, 250, size=n)]
    dst = [f"192.168.10.{int(x)}" for x in rng.choice([3, 5, 9, 12, 15], size=n)]
    df.insert(0, "Destination IP", dst)
    df.insert(0, "Source Port", rng.integers(1025, 65535, size=n))
    df.insert(0, "Source IP", src)
    df.insert(0, "Flow ID", [f"{d}-{s}-{p}" for d, s, p in zip(dst, src, df["Destination Port"])])

    # Real CICIDS2017 rate columns contain Infinity / NaN; reproduce that so cleaning is exercised.
    bad = rng.choice(n, size=max(1, n // 200), replace=False)
    df["Flow Bytes/s"] = df["Flow Bytes/s"].astype(object)
    df.loc[bad[: len(bad) // 2], "Flow Bytes/s"] = "Infinity"
    df.loc[bad[len(bad) // 2:], "Flow Packets/s"] = np.nan
    # ...and some exact duplicate flows.
    dups = df.sample(n=max(1, n // 100), random_state=seed)
    df = pd.concat([df, dups], ignore_index=True)
    return df.sample(frac=1.0, random_state=seed).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("../data/synthetic/synthetic_cicids_like.csv"))
    parser.add_argument("--rows", type=int, default=30000)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df = generate(args.rows, args.seed)
    df.to_csv(args.out, index=False)
    (args.out.parent / "README.txt").write_text(
        "SYNTHETIC DATA. Generated by backend/scripts/generate_synthetic_data.py for smoke testing only.\n"
        "It is not real network traffic and not the CICIDS2017 dataset.\n"
    )
    print(f"Wrote {len(df)} synthetic rows to {args.out}")
    print(df["Label"].value_counts().to_string())


if __name__ == "__main__":
    main()
