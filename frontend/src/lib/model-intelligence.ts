export type ExplanationFeature = {
  name: string;
  label: string;
  value: string | number;
  unit: string | null;
  derived: boolean;
  transformed_features: string[];
  contribution: number;
};

export type PredictionExplanation = {
  prediction_id: number;
  model_version: string;
  method: string;
  output_unit: "raw_margin_log_odds";
  baseline: number;
  raw_output: number;
  failure_score: number;
  features: ExplanationFeature[];
};

export type ModelIntelligence = {
  metadata: {
    model_name: string;
    model_version: string;
    algorithm: string;
    input_features: string[];
    training_observations: number;
    training_failures: number;
    scale_pos_weight: number;
    thresholds: { primary: number; review: number; high_priority: number };
    feature_engineering: { thermal_gap?: boolean };
    dependencies: Record<string, string>;
  };
  global_importance: {
    dataset_split: "training";
    sample_size: number;
    split_seed: number;
    sample_seed: number;
    method: string;
    shap_version: string;
    features: { name: string; label: string; mean_absolute_shap: number }[];
  } | null;
  evaluation: {
    dataset: string;
    test_observations: number;
    test_failures: number;
    average_precision: number;
    primary_threshold_results: {
      threshold: number;
      accuracy: number;
      precision: number;
      recall: number;
      f1: number;
      true_positive: number;
      false_positive: number;
      true_negative: number;
      false_negative: number;
    };
  } | null;
};

export function marginText(value: number, signed = false) {
  const formatted = value.toFixed(4);
  return signed && value > 0 ? `+${formatted}` : formatted;
}
