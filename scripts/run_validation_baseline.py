from pprint import pprint

from sklearn.dummy import DummyClassifier
from sklearn.model_selection import train_test_split

from fleetmind.data.split import load_dataset, split_dataset
from fleetmind.evaluation.validation import evaluate_model

df = load_dataset("data/raw/ai4i2020.csv")

X_train, X_test, y_train, y_test = split_dataset(df)

X_fit, X_val, y_fit, y_val = train_test_split(
    X_train,
    y_train,
    test_size=0.20,
    stratify=y_train,
    random_state=42,
)

model = DummyClassifier(strategy="prior")
model.fit(X_fit, y_fit)

results = evaluate_model(model, X_val, y_val)

print("=== TRAINING-ONLY VALIDATION BASELINE ===")
print(f"Fit observations: {len(X_fit)}")
print(f"Validation observations: {len(X_val)}")
print(f"Validation failure rate: {y_val.mean():.4%}")

pprint(results)
