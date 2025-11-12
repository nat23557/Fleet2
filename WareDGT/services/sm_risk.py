from .dashboard_anomalies import get_anomaly_alerts


def score():
    alerts = get_anomaly_alerts().get("alerts", [])
    weights = {"high": 3, "medium": 2, "low": 1}
    total = sum(weights.get(a.get("severity", "low"), 1) for a in alerts)
    score = min(100, total * 8)
    reasons = [a.get("title", "") for a in alerts[:5]]
    return {"score": score, "reasons": reasons}
