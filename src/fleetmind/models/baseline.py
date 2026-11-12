from sklearn.dummy import DummyClassifier

from fleetmind.data.split import load_dataset, split_dataset


def run_dummy_baseline(dataset_path: str):
    """Train and evaluate a majority-class baseline."""
    df = load_dataset(dataset_path)

    X_train, X_test, y_train, y_test = split_dataset(df)

    model = DummyClassifier(strategy="most_frequent")
    model.fit(X_train, y_train)

    predictions = model.predict(X_test)

    return model, y_test, predictions
