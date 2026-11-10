def test_fleetmind_environment():
    import fastapi
    import numpy
    import pandas
    import sklearn
    import xgboost

    assert numpy.__version__
    assert pandas.__version__
    assert sklearn.__version__
    assert xgboost.__version__
    assert fastapi.__version__
