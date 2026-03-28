# PCOS Risk Score System Documentation

## Overview

The AI-MSHM system provides a comprehensive PCOS risk assessment through a **Weighted Ensemble** approach that combines predictions from 4 different ML models. The system also includes a **Per-Model Escalation** mechanism to notify healthcare providers when risk levels require attention.

---

## 1. Risk Score Calculation

### 1.1 Data Sources (4 Models)

| Model | Data Source | Frequency | Diseases Assessed |
|-------|-------------|----------|------------------|
| **Symptom** | Daily check-ins (morning/evening) | Daily | Infertility, Dysmenorrhea, PMDD, T2D, CVD, Endometrial |
| **Menstrual** | Period logging & cycle tracking | Monthly | Infertility, Dysmenorrhea, PMDD, Endometrial, T2D, CVD |
| **rPPG/HRV** | Heart rate variability capture | As needed | CVD, T2D, Metabolic, Stress, HeartFailure, Infertility |
| **Mood** | Weekly tools (PHQ-4, affect) | Weekly | T2D, Metabolic Syndrome, CVD, Stroke, Infertility (via mood correlations) |

### 1.2 Weighted Ensemble Calculation

Instead of using `MAX(all_model_scores)` which just picks the highest risk, we use a **weighted ensemble** approach:

```
Disease Score = Σ (Model_Prediction × Model_Weight)
```

#### Default Weight Configuration Per Disease

| Disease | Symptom | Menstrual | rPPG | Mood |
|--------|--------|-----------|------|------|
| **PCOS** | 30% | 35% | 20% | 15% |
| **CVD** | 20% | 20% | 40% | 20% |
| **T2D** | 25% | 25% | 35% | 15% |
| **Infertility** | 25% | 40% | 20% | 15% |
| **Dysmenorrhea** | 40% | 35% | 10% | 15% |
| **Metabolic** | 20% | 20% | 45% | 15% |
| **MentalHealth** | 20% | 15% | 25% | 40% |
| **Stroke** | 20% | 20% | 35% | 25% |
| **Endometrial** | 30% | 45% | 15% | 10% |

### 1.3 Clinical Rules Engine

Clinical rules apply **boosts** to scores based on Rotterdam Criteria and clinical knowledge:

| Rule | Condition | Boost |
|------|-----------|-------|
| **Rotterdam 2 Criteria Met** | Oligomenorrhea + Hyperandrogenism signs | +5% |
| **Rotterdam 3 Criteria Met** | All 3 criteria detected | +10% |
| **Metabolic-Reproductive Cluster** | High metabolic stress + reproductive dysfunction | +5% |
| **Mood-rPPG Stress Stack** | Both mood & rPPG stress at Moderate+ | +3% |
| **Severe Amplification** | 2+ models show Severe/Extreme | +5% |

**Maximum Total Boost: 25%**

### 1.4 PCOS-Specific Score

The PCOS-specific score is calculated using PCOS weights plus applicable clinical rule boosts:

```python
pcos_score = weighted_ensemble_score + clinical_boosts
pcos_score = min(pcos_score, 1.0)  # Cap at 100%
```

### 1.5 Overall Risk Score

The overall risk is the **average of all disease scores**:

```python
overall_risk = mean(all_disease_scores)
```

---

## 2. Risk Tiers

| Tier | Score Range | Color | Action |
|------|-------------|-------|--------|
| **Low** | 0.00 - 0.24 | Green | Normal monitoring |
| **Moderate** | 0.25 - 0.49 | Yellow/Amber | Close monitoring recommended |
| **High** | 0.50 - 0.74 | Orange | Healthcare provider consultation |
| **Critical** | 0.75 - 1.00 | Red | Immediate medical attention |

---

## 3. Dashboard Risk Score

### 3.1 Location
- **Path**: `/dashboard`
- **Displayed in**: Risk Card component

### 3.2 Data Flow

```
1. User completes check-ins (morning/evening)
2. → Triggers comprehensive inference
3. → ComprehensivePredictionResult created/updated
4. → Dashboard fetches from GET /api/v1/predictions/comprehensive/
5. → Displays final_risk_score and risk_tier
```

### 3.3 Dashboard Display Components

| Component | Source | Description |
|----------|--------|-------------|
| **Risk Score Badge** | `final_risk_score` | Numeric score (0-100) |
| **Risk Tier Badge** | `risk_tier` | Low/Moderate/High/Critical |
| **Data Completeness** | `data_completeness_pct` | Percentage of layers available |
| **Active Layers** | `data_layers_used` | Which models have data |
| **Escalation Status** | `escalated_to_phc`, `escalated_to_fmc` | Boolean flags |

### 3.4 Dashboard Trigger Points

The comprehensive prediction is triggered when:
- Morning check-in completed
- Evening check-in completed
- Period logged
- rPPG measurement captured
- Mood tracking completed
- Manual refresh requested

---

## 4. PCOSRiskScore Page (`/risk-score`)

### 4.1 Purpose
Detailed view of risk assessment with:
- Risk gauge visualization
- Per-model breakdown
- Disease-specific scores
- Clinical rules explanation

### 4.2 Components Displayed

#### A. Risk Gauge
- Semi-circular gauge with needle animation
- Color gradient: Green → Yellow → Orange → Red
- Shows current score and tier

#### B. PCOS-Specific Score Card
- Teal background highlight
- Weighted ensemble score with clinical adjustments
- Different from overall risk score

#### C. Per-Disease Scores (Expandable)
- All 9 disease scores displayed
- Horizontal bar chart visualization
- Color-coded by risk level

#### D. Clinical Rules Applied
- Lists which clinical rules triggered
- Shows Rotterdam criteria evaluation
- Displays metabolic/mood stack alerts

#### E. Calculation Breakdown (Expandable)
- "How was this score calculated?" button
- Shows model weights used
- Explains clinical boosts applied

#### F. Model Predictions Section
- Symptom Check-ins
- Menstrual Tracking
- rPPG/HRV
- Mood Tracking

#### G. Contributing Factors
- SHAP feature importance
- Top 5 risk drivers

### 4.3 API Response Structure

```json
{
  "data": {
    "id": "uuid",
    "final_risk_score": 0.42,
    "risk_tier": "Moderate",
    "pcos_specific_score": 0.45,
    "per_disease_scores": {
      "PCOS": 0.42,
      "CVD": 0.38,
      "T2D": 0.35,
      ...
    },
    "all_predictions": {
      "symptom": {...},
      "menstrual": {...},
      "rppg": {...},
      "mood": {...}
    },
    "data_layers_used": ["symptom", "menstrual", "rppg", "mood"],
    "data_completeness_pct": 100,
    "clinical_rules_triggered": ["metabolic_stress"],
    "weights_used": {
      "PCOS": {"symptom": 0.30, "menstrual": 0.35, ...}
    },
    "calculation_breakdown": {
      "base_scores": {...},
      "boost_applied": 0.05,
      "clinical_rules_details": {...}
    },
    "highest_risk_disease": "CVD",
    "highest_risk_model": "rppg",
    "computed_at": "2026-03-28T00:00:00Z"
  }
}
```

---

## 5. Escalation System

### 5.1 Escalation Triggers

Escalation occurs when **any model** shows **Moderate or higher** severity.

| Severity | PHC Notification | FMC Notification |
|----------|-----------------|-------------------|
| Minimal | No | No |
| Mild | No | No |
| **Moderate** | ✅ Yes | No |
| Severe | ✅ Yes | ✅ Yes |
| Extreme | ✅ Yes | ✅ Yes |

### 5.2 Per-Model Escalation

Each model independently triggers escalation:

#### A. Symptom Model Escalation
- **Trigger**: Check-in completion
- **Condition**: PHQ-4 ≥ 5 or mF-G ≥ 3
- **Endpoint**: `POST /api/v1/predictions/escalate/symptom/`
- **Notification**: Triggers PHC/FMC based on severity

#### B. Mood Model Escalation
- **Trigger**: Weekly tools completion
- **Condition**: Any mood prediction at Moderate+
- **Endpoint**: `POST /api/v1/predictions/escalate/mood/`
- **Called from**: `CombinedResults.tsx`

#### C. Menstrual Model Escalation
- **Trigger**: Period logging
- **Condition**: Any menstrual prediction at Moderate+
- **Endpoint**: `POST /api/v1/predictions/escalate/menstrual/`
- **Called from**: `PeriodLogging.tsx`

#### D. rPPG Model Escalation
- **Trigger**: rPPG session capture
- **Condition**: Any rPPG prediction at Moderate+
- **Endpoint**: `POST /api/v1/predictions/escalate/rppg/`
- **Called from**: `Step6rPPG.tsx`, `RppgCaptureScreen.tsx`

### 5.3 Escalation Flow

```
1. User completes health activity
2. → ML model runs inference
3. → Prediction score calculated
4. → Severity determined
5. IF severity >= Moderate:
   → Create PHCPatientRecord
   → Send notification to PHC
   IF severity >= Severe:
     → Send notification to FMC
6. → Escalation logged in database
7. → Patient sees "Escalated" badge (future feature)
```

### 5.4 Notification Content

**PHC Notification**:
```
Patient alert: Moderate Cardiovascular

Registered patient [Name] has Moderate Cardiovascular risk (47/100). Review recommended.
```

**FMC Notification**:
```
Urgent: Severe PCOS Risk

Patient [Name] requires immediate specialist review. Risk level: Severe (78/100).
```

### 5.5 Escalation Database Fields

| Field | Type | Description |
|-------|------|-------------|
| `escalated_to_phc` | Boolean | PHC was notified |
| `escalated_to_fmc` | Boolean | FMC was notified |
| `patient_notified` | Boolean | Patient was notified |

---

## 6. Admin Configuration

### 6.1 Ensemble Weight Configuration

Admins can adjust model weights via PHC Settings:

**Endpoint**: `GET/PUT /api/v1/predictions/ensemble-config/`

| Field | Type | Validation |
|-------|------|------------|
| `disease_name` | String | Required, unique |
| `symptom_weight` | Float | 0.0 - 1.0 |
| `menstrual_weight` | Float | 0.0 - 1.0 |
| `rppg_weight` | Float | 0.0 - 1.0 |
| `mood_weight` | Float | 0.0 - 1.0 |

**Validation Rule**: All 4 weights must sum to 1.0

### 6.2 Clinical Rule Boosts

| Field | Default | Max | Description |
|-------|---------|-----|-------------|
| `rotterdam_2_criteria_boost` | 0.05 | 0.20 | +5% for 2 Rotterdam criteria |
| `rotterdam_3_criteria_boost` | 0.10 | 0.30 | +10% for 3 criteria |
| `metabolic_reproductive_boost` | 0.05 | 0.20 | +5% for metabolic cluster |
| `mood_rppg_stress_boost` | 0.03 | 0.20 | +3% for mood-stress stack |

---

## 7. Database Models

### 7.1 ComprehensivePredictionResult

Main model storing unified prediction:

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `user` | FK(User) | Patient reference |
| `final_risk_score` | Float | Overall risk (0-1) |
| `risk_tier` | Enum | Low/Moderate/High/Critical |
| `pcos_specific_score` | Float | PCOS-specific score with boosts |
| `per_disease_scores` | JSON | All disease scores |
| `symptom_predictions` | JSON | Raw symptom model output |
| `menstrual_predictions` | JSON | Raw menstrual model output |
| `rppg_predictions` | JSON | Raw rPPG model output |
| `mood_predictions` | JSON | Raw mood model output |
| `data_layers_used` | JSON | List of active layers |
| `data_completeness_pct` | Int | Percentage complete (0-100) |
| `severity_flags` | JSON | Rotterdam criteria flags |
| `clinical_rules_triggered` | JSON | List of applied rules |
| `weights_used` | JSON | Weights used in calculation |
| `calculation_breakdown` | JSON | Full calculation details |
| `highest_risk_disease` | String | Disease with highest score |
| `highest_risk_model` | String | Model that contributed most |
| `escalated_to_phc` | Boolean | PHC escalation flag |
| `escalated_to_fmc` | Boolean | FMC escalation flag |
| `computed_at` | DateTime | When calculated |

### 7.2 EnsembleWeightConfig

Stores admin-configurable weights:

| Field | Type | Description |
|-------|------|-------------|
| `id` | Auto | Primary key |
| `disease_name` | String | Disease identifier (unique) |
| `symptom_weight` | Float | Symptom model weight |
| `menstrual_weight` | Float | Menstrual model weight |
| `rppg_weight` | Float | rPPG model weight |
| `mood_weight` | Float | Mood model weight |
| `rotterdam_2_criteria_boost` | Float | Clinical rule boost |
| `rotterdam_3_criteria_boost` | Float | Clinical rule boost |
| `metabolic_reproductive_boost` | Float | Clinical rule boost |
| `mood_rppg_stress_boost` | Float | Clinical rule boost |
| `is_active` | Boolean | Configuration active flag |

---

## 8. API Endpoints

### 8.1 Prediction Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/predictions/comprehensive/` | GET | Patient | Get stored prediction |
| `/predictions/comprehensive/` | POST | Patient | Trigger new prediction |
| `/predictions/latest/` | GET | Patient | Latest legacy prediction |
| `/predictions/history/` | GET | Patient | Prediction history |
| `/predictions/<id>/` | GET | Patient | Single prediction |
| `/predictions/trigger/` | POST | Admin | Manual trigger |

### 8.2 Escalation Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/predictions/escalate/mood/` | POST | Patient | Mood escalation |
| `/predictions/escalate/menstrual/` | POST | Patient | Menstrual escalation |
| `/predictions/escalate/rppg/` | POST | Patient | rPPG escalation |

### 8.3 Admin Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/predictions/ensemble-config/` | GET | Admin | List all weights |
| `/predictions/ensemble-config/<disease>/` | PUT | Admin | Update disease weights |
| `/predictions/ensemble-config/reset/` | POST | Admin | Reset to defaults |

---

## 9. Frontend Integration

### 9.1 PCOSRiskScore Page Flow

```
1. Component mounts
2. → Call predictionService.getComprehensive()
3. → Set comprehensive state
4. → Calculate derived values (tier, color, etc.)
5. → Render risk gauge
6. → Render disease scores (if expanded)
7. → Render clinical rules (if any triggered)
8. → Render calculation breakdown (if expanded)
```

### 9.2 Escalation Trigger Points

| Page | Trigger | Service Call |
|------|---------|--------------|
| `CombinedResults.tsx` | Mood predictions loaded | `predictionService.escalateMood()` |
| `PeriodLogging.tsx` | Menstrual predictions loaded | `predictionService.escalateMenstrual()` |
| `Step6rPPG.tsx` | rPPG session captured | `predictionService.escalateRppg()` |
| `RppgCaptureScreen.tsx` | rPPG session captured | `predictionService.escalateRppg()` |

### 9.3 TypeScript Interfaces

```typescript
interface ComprehensivePrediction {
  id: string;
  final_risk_score: number;
  risk_tier: string;
  pcos_specific_score?: number;
  per_disease_scores?: Record<string, number>;
  all_predictions: {
    symptom: Record<string, DiseasePrediction>;
    menstrual: Record<string, DiseasePrediction>;
    rppg: Record<string, DiseasePrediction>;
    mood: Record<string, DiseasePrediction>;
  };
  data_layers_used: string[];
  clinical_rules_triggered?: string[];
  weights_used?: Record<string, Record<string, number>>;
  calculation_breakdown?: CalculationBreakdown;
  escalated_to_phc: boolean;
  escalated_to_fmc: boolean;
}
```

---

## 10. Example Calculations

### Example 1: PCOS Score with Clinical Boost

**Given Data**:
- Symptom CVD: 0.12 (Minimal)
- Menstrual CVD: 0.47 (Moderate)
- rPPG CVD: 0.63 (High)
- Mood CVD: 0.43 (Moderate)

**CVD Weighted Score**:
```
= (0.12 × 0.20) + (0.47 × 0.20) + (0.63 × 0.40) + (0.43 × 0.20)
= 0.024 + 0.094 + 0.252 + 0.086
= 0.456 → Moderate
```

**With Metabolic Stress Boost**:
```
= 0.456 + 0.05 = 0.506 → High
```

### Example 2: PCOS-Specific Score

**Given Data**:
- PCOS base score: 0.42
- Rotterdam criteria met (2): +0.05
- Metabolic stress: +0.05

**PCOS Score**:
```
= 0.42 + 0.05 + 0.05 = 0.52 → High
```

---

## 11. Troubleshooting

### Issue: No per_disease_scores in response

**Cause**: Old prediction record (before weighted ensemble implementation)

**Solution**: Trigger a new prediction via POST to `/api/v1/predictions/comprehensive/`

### Issue: Weights showing as undefined

**Cause**: EnsembleWeightConfig not seeded

**Solution**: Run migration `0003_ensembleweightconfig.py` which seeds default weights

### Issue: Escalations not firing

**Cause**: Frontend not calling escalation endpoints

**Solution**: Verify escalation service calls in CombinedResults.tsx, PeriodLogging.tsx, Step6rPPG.tsx

### Issue: 500 Error on comprehensive endpoint

**Cause**: Migration not run on server

**Solution**: Ensure `python manage.py migrate predictions` runs on deployment

---

## 12. Future Enhancements

1. **SHAP Feature Integration**: Add detailed feature contributions to comprehensive predictions
2. **Trend Analysis**: Track score changes over time
3. **Patient Notifications**: Alert patients when escalation occurs
4. **Configurable Boosts**: Allow admin to adjust clinical rule boost values
5. **Model Retraining Triggers**: Flag when model performance degrades

---

*Document Version: 2.0*
*Last Updated: March 28, 2026*
