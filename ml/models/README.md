# Demo XGBoost artifact

`xgboost_model.pkl` is the small **xgb_v3** booster used by `risk.ml_layer` (`SENTINALPAY_XGB_MODEL` defaults here).

- Evaluation data: synthetic PaySim, chronological 60/20/20. Not a labeled UPI holdout.
- Do not treat `xgboost_metrics.json` as live fraud-detection accuracy.
- Retrain locally only if `dataset/PS_20174392719_1491204439457_log.csv` is already on disk: `py -3 ml/train_xgboost.py`
- Autoencoder `.keras` files and PaySim CSV stay gitignored.
