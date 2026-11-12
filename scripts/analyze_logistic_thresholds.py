import pandas as pd
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import train_test_split

from fleetmind.data.split import load_dataset, split_dataset
from fleetmind.models.logistic import build_logistic_pipeline

df = load_dataset("data/raw/ai4i2020.csv")

X_train, _, y_train, _ = split_dataset(df)

X_fit, X_val, y_fit, y_val = train_test_split(
    X_train,
    y_train,
    test_size=0.20,
    stratify=y_train,
    random_state=42,
)

model = build_logistic_pipeline()
model.fit(X_fit, y_fit)

scores = model.predict_proba(X_val)[:, 1]

thresholds = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]

results = []

for threshold in thresholds:
    predictions = (scores >= threshold).astype(int)

    tn, fp, fn, tp = confusion_matrix(y_val, predictions, labels=[0, 1]).ravel()

    results.append(
        {
            "Threshold": threshold,
            "Precision": precision_score(y_val, predictions, zero_division=0),
            "Recall": recall_score(y_val, predictions, zero_division=0),
            "F1": f1_score(y_val, predictions, zero_division=0),
            "TP": tp,
            "FP": fp,
            "FN": fn,
            "TN": tn,
            "Alerts": tp + fp,
        }
    )

results_df = pd.DataFrame(results)

print("=== LOGISTIC REGRESSION THRESHOLD ANALYSIS ===")
print(results_df.round(4).to_string(index=False))
