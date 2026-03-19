"""
apps/predictions/ml_pipeline.py
═════════════════════════════════
Feature engineering and model inference.
Mirrors the notebook (symptom_intensity_logging_RIsk_Score.ipynb) exactly.

Pipeline:
  1. Load 28-day daily rows from DailyCheckinSummary
  2. Aggregate into patient-level feature vector (means, slopes, phase splits, deltas)
  3. Compute intermediate flags (HighAndrogen, HighAcne, etc.)
  4. Load pkl models and run inference (classifier + regressor per disease)
  5. Compute severity categories from predicted scores
  6. Return structured PredictionOutput dataclass

pkl bundle structure (confirmed from shell inspection):
  {
    'classifiers':    {'Infertility': XGBClassifier, 'Dysmenorrhea': ..., ...},
    'regressors':     {'Infertility': XGBRegressor,  'Dysmenorrhea': ..., ...},
    'scaler':         StandardScaler,
    'feature_names':  [...26 feature names in order...],
    'flag_thresholds':{'Infertility': 0.4, ...},
    'severity_bins':  [...],
    'severity_labels':[...],
    'diseases':       [...],
    'model_metrics':  {...},
    'trained_at':     '...',
    ...
  }
"""
import logging
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── Path to pkl model bundle — deployed under ml/ ─────────────────────────────
ML_DIR        = Path(__file__).resolve().parent.parent.parent / "ml"
PIPELINE_PATH = ML_DIR / "ai_mshm_symptom_pipeline.pkl"

# ── Severity bins matching notebook ───────────────────────────────────────────
SEVERITY_BINS   = [-0.001, 0.19, 0.39, 0.59, 0.79, 1.001]
SEVERITY_LABELS = ["Minimal", "Mild", "Moderate", "Severe", "Extreme"]

# ── Disease names — must match pkl classifiers/regressors keys exactly ─────────
DISEASES = ["Infertility", "Dysmenorrhea", "PMDD", "T2D", "CVD", "Endometrial"]

# ── Feature names — must match pkl feature_names order exactly ────────────────
# Confirmed from: print(p["feature_names"])
FEATURES = [
    "pelvic_28d", "fatigue_28d", "pain_28d", "breast_28d",
    "acne_28d", "mfg_28d", "bloating_28d", "sbs_28d",
    "pelvic_men", "pelvic_lut", "pelvic_fol",
    "fatigue_men", "fatigue_lut", "fatigue_fol",
    "pain_men", "breast_lut", "sbs_lut", "sbs_fol",
    "breast_delta", "fatigue_delta", "sbs_delta", "pain_delta",
    "sbs_slope", "fatigue_slope",
    "bloating_peak", "sbs_std",
]

# ── Flag thresholds — confirmed from: print(p["flag_thresholds"]) ─────────────
FLAG_THRESHOLDS = {
    "Infertility":  0.40,
    "Dysmenorrhea": 0.35,
    "PMDD":         0.25,
    "T2D":          0.40,
    "CVD":          0.40,
    "Endometrial":  0.35,
}

# ── SBS computation constants from notebook Step 1 ────────────────────────────
# PCOS=0: mFG max = 16, PCOS=1: mFG max = 25
MFG_MAX_DEFAULT = 25.0
ACNE_MAX        = 3.0
VAS_MAX         = 10.0


# ─────────────────────────────────────────────────────────────────────────────
# Output dataclasses
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DiseaseResult:
    score:     float
    flag:      bool
    severity:  str
    risk_prob: float


@dataclass
class PredictionOutput:
    feature_vector:        dict
    raw_daily_data:        list
    days_of_data:          int
    data_completeness_pct: float
    symptom_burden_score:  Optional[float]
    infertility:           Optional[DiseaseResult] = None
    dysmenorrhea:          Optional[DiseaseResult] = None
    pmdd:                  Optional[DiseaseResult] = None
    t2d:                   Optional[DiseaseResult] = None
    cvd:                   Optional[DiseaseResult] = None
    endometrial:           Optional[DiseaseResult] = None
    model_version:         str = "v1.0"
    status:                str = "success"
    error_message:         str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Model loader — singleton, loads once and caches
# ─────────────────────────────────────────────────────────────────────────────

_pipeline_cache = None


def load_pipeline() -> dict:
    """
    Load the pkl bundle once and cache in memory.
    Raises FileNotFoundError if the pkl is not in ml/ directory.
    """
    global _pipeline_cache
    if _pipeline_cache is not None:
        return _pipeline_cache

    if not PIPELINE_PATH.exists():
        raise FileNotFoundError(
            f"ML pipeline not found at {PIPELINE_PATH}. "
            "Copy ai_mshm_symptom_pipeline.pkl into the ml/ directory."
        )

    with open(PIPELINE_PATH, "rb") as f:
        _pipeline_cache = pickle.load(f)

    # Log what was loaded for debugging
    trained_at = _pipeline_cache.get("trained_at", "unknown")
    diseases   = list(_pipeline_cache["classifiers"].keys())
    logger.info("ML pipeline loaded: trained_at=%s diseases=%s", trained_at, diseases)

    return _pipeline_cache


# ─────────────────────────────────────────────────────────────────────────────
# Severity mapping — mirrors notebook severity bins
# ─────────────────────────────────────────────────────────────────────────────

def map_severity(score: float) -> str:
    if score <= 0.19:
        return "Minimal"
    elif score <= 0.39:
        return "Mild"
    elif score <= 0.59:
        return "Moderate"
    elif score <= 0.79:
        return "Severe"
    else:
        return "Extreme"


# ─────────────────────────────────────────────────────────────────────────────
# Feature engineering helpers — mirror notebook Steps 1–2
# ─────────────────────────────────────────────────────────────────────────────

def _safe_mean(values: list) -> Optional[float]:
    """Mean of non-null values. Returns None if no values."""
    clean = [v for v in values if v is not None]
    return float(np.mean(clean)) if clean else None


def _safe_std(values: list) -> Optional[float]:
    """Std dev of non-null values. Requires >= 3 values (same as notebook safe_std)."""
    clean = [v for v in values if v is not None]
    return float(np.std(clean, ddof=1)) if len(clean) >= 3 else None


def _safe_slope(values: list) -> Optional[float]:
    """Linear slope of non-null values. Requires >= 3 values (same as notebook safe_slope)."""
    from scipy.stats import linregress
    clean = [v for v in values if v is not None]
    if len(clean) < 3:
        return None
    return float(linregress(range(len(clean)), clean).slope)


def _compute_sbs(row: dict, pcos_label: int = 0) -> Optional[float]:
    """
    Symptom Burden Score — exactly as in notebook Step 1 compute_sbs().
    Returns None if any required field is missing (mFG null = no SBS).

    pcos_label 0 = no PCOS (mFG max 16)
    pcos_label 1 = PCOS    (mFG max 25)
    """
    mfg_max = 16.0 if pcos_label == 0 else 25.0

    pelvic  = row.get("Pelvic_Pressure_VAS")
    fatigue = row.get("Fatigue_MFI5_VAS")
    pain    = row.get("Painful_Touch_VAS")
    breast  = row.get("Breast_Soreness_VAS")
    acne    = row.get("Acne_Severity_Likert")
    mfg     = row.get("Hirsutism_mFG_Score")

    # All 6 fields required — if mFG is null (not submitted yet), SBS is null
    if any(v is None for v in [pelvic, fatigue, pain, breast, acne, mfg]):
        return None

    sbs = (
        pelvic  / VAS_MAX  * 10 * 0.25 +
        fatigue / VAS_MAX  * 10 * 0.25 +
        pain    / VAS_MAX  * 10 * 0.20 +
        breast  / VAS_MAX  * 10 * 0.15 +
        acne    / ACNE_MAX * 10 * 0.10 +
        mfg     / mfg_max  * 10 * 0.05
    )
    return round(float(sbs), 4)


# ─────────────────────────────────────────────────────────────────────────────
# Feature vector builder — mirrors notebook Step 2 aggregation
# ─────────────────────────────────────────────────────────────────────────────

def build_feature_vector(daily_rows: list[dict], pcos_label: int = 0) -> dict:
    """
    Convert list of daily summary dicts into the 26-feature patient vector.
    daily_rows: output of DailySummaryService.get_28_day_data()

    Notebook Step 2 does groupby().agg(mean, slope, std) over all patient rows.
    We do the same here for one patient over their available days.

    Returns dict with all 26 FEATURES keys. None where data is missing.
    Missing values are filled with 0.0 before model inference.
    """
    if not daily_rows:
        return {f: None for f in FEATURES}

    # Compute SBS for each daily row first (needed for sbs_28d, sbs_slope, etc.)
    for row in daily_rows:
        row["SBS"] = _compute_sbs(row, pcos_label=pcos_label)

    # Split rows by cycle phase for phase-specific means
    phase_rows = {
        "Menstrual":  [r for r in daily_rows if r.get("Cycle_Phase") == "Menstrual"],
        "Luteal":     [r for r in daily_rows if r.get("Cycle_Phase") == "Luteal"],
        "Follicular": [r for r in daily_rows if r.get("Cycle_Phase") == "Follicular"],
    }

    def phase_mean(phase, col):
        return _safe_mean([r.get(col) for r in phase_rows[phase]])

    # ── 28-day means (all phases combined) — notebook pelvic_28d, fatigue_28d etc ──
    all_pelvic   = [r.get("Pelvic_Pressure_VAS")  for r in daily_rows]
    all_fatigue  = [r.get("Fatigue_MFI5_VAS")     for r in daily_rows]
    all_pain     = [r.get("Painful_Touch_VAS")     for r in daily_rows]
    all_breast   = [r.get("Breast_Soreness_VAS")   for r in daily_rows]
    all_acne     = [r.get("Acne_Severity_Likert")  for r in daily_rows]
    all_mfg      = [r.get("Hirsutism_mFG_Score")   for r in daily_rows]
    all_bloating = [r.get("Bloating_Delta_cm")     for r in daily_rows]
    all_sbs      = [r.get("SBS")                   for r in daily_rows]

    pelvic_28d   = _safe_mean(all_pelvic)
    fatigue_28d  = _safe_mean(all_fatigue)
    pain_28d     = _safe_mean(all_pain)
    breast_28d   = _safe_mean(all_breast)
    acne_28d     = _safe_mean(all_acne)
    mfg_28d      = _safe_mean(all_mfg)
    bloating_28d = _safe_mean(all_bloating)
    sbs_28d      = _safe_mean(all_sbs)

    # ── Phase-specific means — notebook pelvic_men, fatigue_lut etc ───────────
    pelvic_men  = phase_mean("Menstrual",  "Pelvic_Pressure_VAS")
    pelvic_lut  = phase_mean("Luteal",     "Pelvic_Pressure_VAS")
    pelvic_fol  = phase_mean("Follicular", "Pelvic_Pressure_VAS")

    fatigue_men = phase_mean("Menstrual",  "Fatigue_MFI5_VAS")
    fatigue_lut = phase_mean("Luteal",     "Fatigue_MFI5_VAS")
    fatigue_fol = phase_mean("Follicular", "Fatigue_MFI5_VAS")

    pain_men    = phase_mean("Menstrual",  "Painful_Touch_VAS")
    breast_lut  = phase_mean("Luteal",     "Breast_Soreness_VAS")
    sbs_lut     = phase_mean("Luteal",     "SBS")
    sbs_fol     = phase_mean("Follicular", "SBS")

    # ── Luteal − Follicular deltas — notebook breast_delta, fatigue_delta etc ──
    # These are the PMDD phase-shift signals
    breast_delta  = (breast_lut  or 0) - (phase_mean("Follicular", "Breast_Soreness_VAS") or 0)
    fatigue_delta = (fatigue_lut or 0) - (fatigue_fol or 0)
    sbs_delta     = (sbs_lut     or 0) - (sbs_fol     or 0)
    pain_delta    = (pain_men    or 0) - (phase_mean("Follicular", "Painful_Touch_VAS") or 0)

    # ── Slopes and variability — notebook sbs_slope, fatigue_slope, sbs_std ───
    sbs_slope     = _safe_slope(all_sbs)
    fatigue_slope = _safe_slope(all_fatigue)
    bloating_peak = max((v for v in all_bloating if v is not None), default=None)
    sbs_std       = _safe_std(all_sbs)

    return {
        "pelvic_28d":    pelvic_28d,
        "fatigue_28d":   fatigue_28d,
        "pain_28d":      pain_28d,
        "breast_28d":    breast_28d,
        "acne_28d":      acne_28d,
        "mfg_28d":       mfg_28d,
        "bloating_28d":  bloating_28d,
        "sbs_28d":       sbs_28d,
        "pelvic_men":    pelvic_men,
        "pelvic_lut":    pelvic_lut,
        "pelvic_fol":    pelvic_fol,
        "fatigue_men":   fatigue_men,
        "fatigue_lut":   fatigue_lut,
        "fatigue_fol":   fatigue_fol,
        "pain_men":      pain_men,
        "breast_lut":    breast_lut,
        "sbs_lut":       sbs_lut,
        "sbs_fol":       sbs_fol,
        "breast_delta":  breast_delta,
        "fatigue_delta": fatigue_delta,
        "sbs_delta":     sbs_delta,
        "pain_delta":    pain_delta,
        "sbs_slope":     sbs_slope,
        "fatigue_slope": fatigue_slope,
        "bloating_peak": bloating_peak,
        "sbs_std":       sbs_std,
    }


def feature_vector_to_array(fv: dict, feature_names: list = None) -> np.ndarray:
    """
    Convert feature dict to numpy array in the exact order the model was trained on.
    Uses feature_names from pkl if available, falls back to FEATURES constant.
    Missing values filled with 0.0 (same as X.fillna(X.median()) in notebook).
    """
    names = feature_names or FEATURES
    row   = [fv.get(f) for f in names]
    arr   = np.array([v if v is not None else np.nan for v in row], dtype=float)
    arr   = np.where(np.isnan(arr), 0.0, arr)
    return arr.reshape(1, -1)


# ─────────────────────────────────────────────────────────────────────────────
# Main inference function
# ─────────────────────────────────────────────────────────────────────────────

def run_inference(daily_rows: list[dict], pcos_label: int = 0) -> PredictionOutput:
    """
    Full inference pipeline for one patient:
      1. Check minimum data requirement (3 days)
      2. Build 26-feature vector from daily rows
      3. Load pkl bundle (cached after first load)
      4. Scale features using saved StandardScaler
      5. Run XGBClassifier + XGBRegressor per disease
      6. Return PredictionOutput with all 6 disease results

    Falls back to rule-based scores if pkl is missing.
    Returns status=insufficient if fewer than 3 days of data.
    """
    days_of_data          = len(daily_rows)
    data_completeness_pct = round(days_of_data / 28 * 100, 1)

    # ── Guard: need at least 3 days to compute meaningful slopes ──────────────
    # Below 3 days, _safe_slope returns None for everything → all features = 0
    # Predictions would be meaningless so we return insufficient instead
    if days_of_data < 3:
        logger.warning("Insufficient data: %d days (need ≥ 3)", days_of_data)
        return PredictionOutput(
            feature_vector={},
            raw_daily_data=daily_rows,
            days_of_data=days_of_data,
            data_completeness_pct=data_completeness_pct,
            symptom_burden_score=None,
            status="insufficient",
            error_message=f"Only {days_of_data} days of data available. Minimum 3 required.",
        )

    # ── Build feature vector from available daily rows ─────────────────────────
    fv  = build_feature_vector(daily_rows, pcos_label=pcos_label)
    sbs = fv.get("sbs_28d")

    # ── Load pkl — fall back to rule-based if missing ──────────────────────────
    try:
        pipeline = load_pipeline()
    except FileNotFoundError as e:
        logger.error("Pipeline file missing: %s", e)
        return _rule_based_fallback(fv, daily_rows, days_of_data, data_completeness_pct, sbs)

    # ── Build feature array in pkl's exact feature order ──────────────────────
    arr = feature_vector_to_array(fv, feature_names=pipeline.get("feature_names"))

    # ── Scale features using the saved StandardScaler ─────────────────────────
    # The notebook scales X before training — must apply same scaler at inference
    scaler = pipeline.get("scaler")
    if scaler is not None:
        arr = scaler.transform(arr)

    # ── Build output object ────────────────────────────────────────────────────
    output = PredictionOutput(
        feature_vector=fv,
        raw_daily_data=daily_rows,
        days_of_data=days_of_data,
        data_completeness_pct=data_completeness_pct,
        symptom_burden_score=round(sbs, 4) if sbs else None,
        model_version=pipeline.get("trained_at", "v1.0"),
    )

    # ── Run inference per disease ──────────────────────────────────────────────
    for disease in DISEASES:
        # Get classifier and regressor from their respective dicts in the pkl
        clf       = pipeline["classifiers"].get(disease)
        reg       = pipeline["regressors"].get(disease)
        # Use threshold from pkl — confirmed matches FLAG_THRESHOLDS exactly
        threshold = pipeline["flag_thresholds"].get(disease, FLAG_THRESHOLDS.get(disease, 0.40))

        if clf is None or reg is None:
            logger.warning("Disease %s not found in pipeline", disease)
            continue

        try:
            # Regressor predicts the continuous risk score 0–1
            pred_score = float(reg.predict(arr)[0])
            pred_score = max(0.0, min(1.0, pred_score))  # clip to valid range

            # Classifier predicts probability of being a positive case
            risk_prob  = float(clf.predict_proba(arr)[0][1])

            # Flag if score meets or exceeds disease-specific threshold
            pred_flag  = pred_score >= threshold

            # Map continuous score to severity category
            severity   = map_severity(pred_score)

            result = DiseaseResult(
                score=round(pred_score, 4),
                flag=bool(pred_flag),
                severity=severity,
                risk_prob=round(risk_prob, 4),
            )

        except Exception as e:
            logger.error("Inference failed for %s: %s", disease, e)
            result = None

        # Set as attribute on output (infertility, dysmenorrhea, pmdd, t2d, cvd, endometrial)
        setattr(output, disease.lower(), result)

    return output


# ─────────────────────────────────────────────────────────────────────────────
# Rule-based fallback — used when pkl is unavailable
# Mirrors notebook Step 4 score formulas exactly
# ─────────────────────────────────────────────────────────────────────────────

def _rule_based_fallback(
    fv: dict, raw_rows: list, days: int, completeness: float, sbs: float
) -> PredictionOutput:
    """
    Computes rule-based risk scores from the feature vector when the pkl model
    is unavailable. Mirrors the formulas from notebook Step 4.
    Returns status=partial so the frontend knows these are estimates not ML scores.
    """
    logger.warning("Using rule-based fallback (pkl not loaded)")

    def clip01(v): return max(0.0, min(1.0, v or 0.0))

    mfg_28d       = fv.get("mfg_28d")       or 0
    acne_28d      = fv.get("acne_28d")       or 0
    fatigue_28d   = fv.get("fatigue_28d")    or 0
    pelvic_28d    = fv.get("pelvic_28d")     or 0
    pain_men      = fv.get("pain_men")       or 0
    pelvic_lut    = fv.get("pelvic_lut")     or 0
    pelvic_men    = fv.get("pelvic_men")     or 0
    bloat_men     = fv.get("bloating_28d")   or 0
    sbs_delta     = fv.get("sbs_delta")      or 0
    breast_delta  = fv.get("breast_delta")   or 0
    fatigue_delta = fv.get("fatigue_delta")  or 0
    fatigue_slope = fv.get("fatigue_slope")  or 0
    bloating_28d  = fv.get("bloating_28d")   or 0
    bloating_peak = fv.get("bloating_peak")  or 0
    pain_28d      = fv.get("pain_28d")       or 0
    sbs_slope     = fv.get("sbs_slope")      or 0

    # Intermediate flags — mirrors notebook Step 3
    high_androgen  = 1 if mfg_28d > 6.0 else 0
    high_acne      = 1 if acne_28d > 1.5 else 0
    rising_fatigue = 1 if fatigue_slope > 0.1 else 0

    def make(score, threshold):
        score = round(clip01(score), 4)
        return DiseaseResult(
            score=score,
            flag=score >= threshold,
            severity=map_severity(score),
            risk_prob=round(score * 0.9, 4),
        )

    # Score formulas mirror notebook Step 4 exactly
    infertility_s = clip01(
        (mfg_28d / 25) * 0.35 + high_androgen * 0.25 +
        (pelvic_lut / 10) * 0.25 + high_acne * 0.15
    )
    dysmenorrhea_s = clip01(
        (pain_men / 10) * 0.45 + (pelvic_men / 10) * 0.35 +
        (bloat_men / 5.54) * 0.20
    )
    pmdd_s = clip01(
        clip01(sbs_delta / 5) * 0.50 +
        clip01(breast_delta / 5) * 0.30 +
        clip01(fatigue_delta / 5) * 0.20
    )
    t2d_s = clip01(
        (fatigue_28d / 10) * 0.50 + rising_fatigue * 0.25 +
        clip01(mfg_28d / 25) * 0.15 + clip01(acne_28d / 3) * 0.10
    )
    cvd_s = clip01(
        (fatigue_28d / 10) * 0.40 + rising_fatigue * 0.25 +
        (pelvic_28d / 10) * 0.20 + (bloating_28d / 5.54) * 0.15
    )
    endometrial_s = clip01(
        (pelvic_28d / 10) * 0.35 + (pain_28d / 10) * 0.30 +
        clip01(sbs_slope / 0.5) * 0.20 +
        (bloating_peak / 5.54) * 0.15
    )

    return PredictionOutput(
        feature_vector=fv,
        raw_daily_data=raw_rows,
        days_of_data=days,
        data_completeness_pct=completeness,
        symptom_burden_score=round(sbs, 4) if sbs else None,
        infertility  = make(infertility_s,  0.40),
        dysmenorrhea = make(dysmenorrhea_s, 0.35),
        pmdd         = make(pmdd_s,         0.25),
        t2d          = make(t2d_s,          0.40),
        cvd          = make(cvd_s,          0.40),
        endometrial  = make(endometrial_s,  0.35),
        model_version="rule-based-fallback",
        status="partial",
        error_message="ML model unavailable — rule-based scores computed.",
    )