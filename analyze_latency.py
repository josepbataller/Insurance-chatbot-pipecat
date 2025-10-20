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

# Directory to save plots
PLOTS_DIR = "plots"
os.makedirs(PLOTS_DIR, exist_ok=True)

# -------------------------------
# 2. Connect to Supabase
# -------------------------------
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# -------------------------------
# 3. Retrieve conversation logs (for total latency) for ALL sessions
# -------------------------------
conv_resp = supabase.table("conversation_logs").select("*").execute()
conv_data = conv_resp.data

if not conv_data:
    print("No conversation logs found.")
    exit()

conv_df = pd.DataFrame(conv_data)
conv_df["timestamp"] = pd.to_datetime(conv_df["timestamp"], utc=True)
conv_df = conv_df.sort_values(["session_id", "timestamp"]).reset_index(drop=True)

# Compute user→assistant total latencies per session
turns = []
for session_id, session_df in conv_df.groupby("session_id"):
    session_df = session_df.reset_index(drop=True)
    for i in range(1, len(session_df)):
        prev = session_df.iloc[i - 1]
        curr = session_df.iloc[i]
        if prev["role"] == "user" and curr["role"] == "assistant":
            latency_ms = (curr["timestamp"] - prev["timestamp"]).total_seconds() * 1000
            turns.append({
                "session_id": session_id,
                "turn_index": len(turns) + 1,
                "latency_ms": latency_ms
            })

total_latency_df = pd.DataFrame(turns)

# -------------------------------
# 4. Retrieve metrics logs (per-module latency) for ALL sessions
# -------------------------------
metrics_resp = supabase.table("metrics_logs").select("*").execute()
metrics_data = metrics_resp.data

if not metrics_data:
    print("No metrics found.")
    exit()

metrics_df = pd.DataFrame(metrics_data)
metrics_df["created_at"] = pd.to_datetime(metrics_df["created_at"], utc=True)
metrics_df = metrics_df.sort_values(["session_id", "created_at"]).reset_index(drop=True)

# Keep only relevant columns and convert to ms
metrics_df = metrics_df[["session_id", "created_at", "processor", "value"]]
metrics_df["value"] = metrics_df["value"] * 1000

# -------------------------------
# Normalize processor names by removing the #N suffix
# -------------------------------
metrics_df["processor_group"] = metrics_df["processor"].str.replace(r"#\d+$", "", regex=True)

# -------------------------------
# 5. Summarize latency per processor/module
# -------------------------------
def summarize_latency(df, total_latency_df):
    summary = df.groupby("processor_group")["value"].agg(
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

# 1️⃣ Print a pretty Markdown-style table (good for reports)
print("\n=== Module Latency Summary (ms) ===\n")
print(summary.to_markdown(floatfmt=".6f"))

# 2️⃣ Also print a simple text version (for plain text reports)
print("\n--- Plain Text Version ---\n")
print(summary.to_string(float_format="{:.6f}".format))

# 3️⃣ Save to CSV
summary_csv_path = os.path.join(PLOTS_DIR, f"session_all_latency_summary.csv")
summary.to_csv(summary_csv_path, sep=';', float_format="%.6f", decimal=',')
print(f"\n✅ Summary table saved to {summary_csv_path}")

# -------------------------------
# 6. Plot latency per processor/module
# -------------------------------
modules = metrics_df["processor_group"].unique()

for module in modules:
    subset = metrics_df[metrics_df["processor_group"] == module]
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

    filename = os.path.join(PLOTS_DIR, f"all_{module}_latency.png")
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

    filename = os.path.join(PLOTS_DIR, f"all_total_latency.png")
    plt.savefig(filename)
    plt.close()
    print(f"Saved plot: {filename}")
else:
    print("\n⚠️ No total conversation latency data available.")

# Unique session IDs from conversation logs
unique_session_ids_conv = conv_df["session_id"].unique()
print("Unique session IDs (conversation logs):", unique_session_ids_conv)

# Unique session IDs from metrics logs
unique_session_ids_metrics = metrics_df["session_id"].unique()
print("Unique session IDs (metrics logs):", unique_session_ids_metrics)

# Optional: combined unique IDs from both tables
all_unique_session_ids = pd.unique(
    list(unique_session_ids_conv) + list(unique_session_ids_metrics)
)
print("All unique session IDs:", all_unique_session_ids)
