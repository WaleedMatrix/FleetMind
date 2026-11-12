from pprint import pprint

from fleetmind.evaluation.metrics import evaluate_classifier
from fleetmind.models.baseline import run_dummy_baseline

model, y_test, predictions = run_dummy_baseline("data/raw/ai4i2020.csv")

results = evaluate_classifier(
    y_true=y_test,
    y_pred=predictions,
)

pprint(results)
