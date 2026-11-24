from pprint import pprint

from sklearn.model_selection import train_test_split

from fleetmind.data.split import load_dataset, split_dataset
from fleetmind.evaluation.validation import evaluate_model
from fleetmind.models.xgboost_model import build_xgboost_pipeline

df = load_dataset("data/raw/ai4i2020.csv")

X_train, _, y_train, _ = split_dataset(df)

X_fit, X_val, y_fit, y_val = train_test_split(
    X_train,
    y_train,
    test_size=0.20,
    stratify=y_train,
    random_state=42,
)

negative_count = (y_fit == 0).sum()
positive_count = (y_fit == 1).sum()

scale_pos_weight = negative_count / positive_count

model = build_xgboost_pipeline(
    scale_pos_weight=scale_pos_weight,
)

model.fit(X_fit, y_fit)

results = evaluate_model(model, X_val, y_val)

print("=== XGBOOST VALIDATION ===")
print(f"Fit observations: {len(X_fit)}")
print(f"Validation observations: {len(X_val)}")
print(f"Scale positive weight: {scale_pos_weight:.2f}")

pprint(results)
