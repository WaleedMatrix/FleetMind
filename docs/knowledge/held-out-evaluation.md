# Frozen held-out evaluation

The repository's final_test_metrics.json records results for xgboost_v1 on 2,000 held-out AI4I observations with 68 labeled failures. Average precision, the threshold-independent ranking metric, was 0.8654788810070985. This report describes benchmark results and is not a field reliability study.

## Primary classification threshold

At the score threshold of 0.50, recorded precision was 0.5841584158415841, recall was 0.8676470588235294, F1 was 0.6982248520710059, and accuracy was 0.9745. The confusion counts were 59 true positives, 42 false positives, 9 false negatives, and 1,890 true negatives. Accuracy must be interpreted alongside precision and recall because failures are a small share of the benchmark.
