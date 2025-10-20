import os
import pandas as pd
import matplotlib.pyplot as plt
from supabase import create_client
from dotenv import load_dotenv

load_dotenv(override=True)

# -------------------------------
# 1. Configuration
# -------------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise EnvironmentError("Please set SUPABASE_URL and SUPABASE_KEY in your environment variables.")

SESSION_ID = input("Enter the session_id you want to analyze: ").strip()

# Directory to save plots
PLOTS_DIR = "plots"
os.makedirs(PLOTS_DIR, exist_ok=True)

# -------------------------------
# 2. Connect to Supabase
# -------------------------------
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# -------------------------------
# 3. Retrieve conversation logs (for total latency)
# -------------------------------
conv_resp = supabase.table("conversation_logs").select("*").eq("session_id", SESSION_ID).execute()
conv_data = conv_resp.data

if not conv_data:
    print(f"No conversation logs found for session_id = {SESSION_ID}")
    exit()

conv_df = pd.DataFrame(conv_data)
conv_df["timestamp"] = pd.to_datetime(conv_df["timestamp"], utc=True)
conv_df = conv_df.sort_values("timestamp").reset_index(drop=True)

# Compute user→assistant total latencies
turns = []
for i in range(1, len(conv_df)):
    prev = conv_df.iloc[i - 1]
    curr = conv_df.iloc[i]
    if prev["role"] == "user" and curr["role"] == "assistant":
        latency_ms = (curr["timestamp"] - prev["timestamp"]).total_seconds() * 1000
        turns.append({"turn_index": len(turns) + 1, "latency_ms": latency_ms})

total_latency_df = pd.DataFrame(turns)

# -------------------------------
# 4. Retrieve metrics logs (per-module latency)
# -------------------------------
metrics_resp = supabase.table("metrics_logs").select("*").eq("session_id", SESSION_ID).execute()
metrics_data = metrics_resp.data

if not metrics_data:
    print(f"No metrics found for session_id = {SESSION_ID}")
    exit()

metrics_df = pd.DataFrame(metrics_data)
metrics_df["created_at"] = pd.to_datetime(metrics_df["created_at"], utc=True)
metrics_df = metrics_df.sort_values("created_at").reset_index(drop=True)

# Keep only relevant columns
metrics_df = metrics_df[["created_at", "processor", "value"]]

# -------------------------------
# 5. Summarize latency per processor/module
# -------------------------------
def summarize_latency(df, total_latency_df):
    summary = df.groupby("processor")["value"].agg(
        mean=lambda x: round(x.mean(), 6),
        median=lambda x: round(x.median(), 6),   # P50
        p90=lambda x: round(x.quantile(0.9), 6),
        max=lambda x: round(x.max(), 6),
        min=lambda x: round(x.min(), 6),
        std=lambda x: round(x.std(), 6)
    )

    # Add total conversation latency as a separate row
    if not total_latency_df.empty:
        total_stats = {
            "mean": round(total_latency_df["latency_ms"].mean(), 6),
            "median": round(total_latency_df["latency_ms"].median(), 6),
            "p90": round(total_latency_df["latency_ms"].quantile(0.9), 6),
            "max": round(total_latency_df["latency_ms"].max(), 6),
            "min": round(total_latency_df["latency_ms"].min(), 6),
            "std": round(total_latency_df["latency_ms"].std(), 6)
        }
        summary.loc["Total conversation"] = total_stats

    return summary

summary = summarize_latency(metrics_df, total_latency_df)
print("\n=== Module Latency Summary (ms) ===")
print(summary)

# -------------------------------
# 6. Plot latency per processor/module
# -------------------------------
modules = metrics_df["processor"].unique()

for module in modules:
    subset = metrics_df[metrics_df["processor"] == module]
    if subset.empty:
        print(f"\n⚠️ No data for {module} in this session.")
        continue

    plt.figure(figsize=(8, 4))
    plt.plot(subset["created_at"], subset["value"], marker="o", linestyle="-")
    plt.title(f"{module.upper()} Latency Over Time")
    plt.xlabel("Time")
    plt.ylabel("Latency (ms)")
    plt.grid(True)
    plt.tight_layout()

    filename = os.path.join(PLOTS_DIR, f"{SESSION_ID}_{module}_latency.png")
    plt.savefig(filename)
    plt.close()
    print(f"Saved plot: {filename}")

# -------------------------------
# 7. Save total conversation latency plot
# -------------------------------
if not total_latency_df.empty:
    plt.figure(figsize=(8, 4))
    plt.plot(total_latency_df["turn_index"], total_latency_df["latency_ms"], marker="o", color="purple")
    plt.title(f"Total Conversation Latency per Turn")
    plt.xlabel("Turn Number")
    plt.ylabel("Latency (ms)")
    plt.grid(True)
    plt.tight_layout()

    filename = os.path.join(PLOTS_DIR, f"{SESSION_ID}_total_latency.png")
    plt.savefig(filename)
    plt.close()
    print(f"Saved plot: {filename}")
else:
    print("\n⚠️ No total conversation latency data available.")
