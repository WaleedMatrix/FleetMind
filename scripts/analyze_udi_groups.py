from fleetmind.data.split import load_dataset, split_dataset

df = load_dataset("data/raw/ai4i2020.csv")

X_train, _, y_train, _ = split_dataset(df)

# Restrict analysis to the original training partition.
train_df = df.loc[X_train.index].copy()

# UDI is used only for diagnostics, never as a model feature.
train_df["udi_group"] = ((train_df["UDI"] - 1) // 1000).astype(int)

failure_modes = ["TWF", "HDF", "PWF", "OSF", "RNF"]

summary = train_df.groupby("udi_group").agg(
    observations=("Machine failure", "size"),
    failures=("Machine failure", "sum"),
    avg_torque=("Torque [Nm]", "mean"),
    avg_rpm=("Rotational speed [rpm]", "mean"),
    avg_tool_wear=("Tool wear [min]", "mean"),
    avg_air_temp=("Air temperature [K]", "mean"),
    avg_process_temp=("Process temperature [K]", "mean"),
)

summary["failure_rate"] = summary["failures"] / summary["observations"]

mode_counts = train_df.groupby("udi_group")[failure_modes].sum()

summary = summary.join(mode_counts)

print("=== UDI GROUP DIAGNOSTICS ===")
print(summary.round(4).to_string())

print("\n=== FAILURE RATES ===")
print(
    summary[["observations", "failures", "failure_rate"]]
    .sort_values("failure_rate", ascending=False)
    .round(4)
    .to_string()
)
