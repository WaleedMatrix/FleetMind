# Interpreting SHAP explanations

FleetMind's TreeExplainer uses the original reading and its matching frozen model. The baseline plus signed feature contributions equals the raw classifier margin in log-odds, within numerical tolerance. A positive contribution raises that margin and a negative one lowers it. The logistic transform produces the uncalibrated score. A SHAP value is not a percentage-point change in failure probability.

## Reading local and global attributions

The waterfall adds signed contributions to the baseline to reach the final raw output. The one-hot machine-type contributions are grouped together and thermal gap remains a separate derived input. Global importance is the mean absolute SHAP magnitude from 512 sampled training observations; it omits direction and depends on the sample and method. Attributions describe the fitted model's behavior, not physical causation.
