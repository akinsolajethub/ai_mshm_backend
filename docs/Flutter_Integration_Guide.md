# Flutter Mobile App Integration Guide
## AI-MSHM PCOS Risk Assessment System

**Version**: 1.2  
**Last Updated**: March 28, 2026  
**For**: Flutter Mobile Developer

---

## Table of Contents

1. [Overview](#overview)
2. [API Base URL](#api-base-url)
3. [Authentication](#authentication)
4. [Core Endpoints](#core-endpoints)
5. [Risk Score Display](#risk-score-display)
6. [Escalation System](#escalation-system)
7. [rPPG/HRV Capture](#rppghrv-capture)
8. [Mood Tracking](#mood-tracking)
9. [Menstrual Tracking](#menstrual-tracking)
10. [Admin Features (PHC)](#admin-features-phc)
11. [Data Models](#data-models)
12. [Error Handling](#error-handling)
13. [Implementation Checklist](#implementation-checklist)

---

## Overview

This guide documents all API changes made to the AI-MSHM system and how to implement them in Flutter.

### Key Features Added:
1. **Weighted Ensemble Scoring** - Combined risk from 4 ML models with configurable weights
2. **Per-Disease Scores** - Individual scores for PCOS, CVD, T2D, Infertility, etc.
3. **Per-Model Escalation** - Healthcare providers notified at model level
4. **Clinical Rules Engine** - Rotterdam criteria and metabolic clustering boosts
5. **rPPG Re-capture** - Users can capture HRV anytime from dashboard
6. **Disease-Specific Notifications** - Notifications show specific disease names (e.g., "PCOS Risk (Infertility)")
7. **Mark All as Read** - Batch notification management
8. **Notification Click Routing** - Tap notification to view patient detail page
9. **PWA Support** - Installable app with manifest

---

## API Base URL

```
Production: https://ai-mshm-backend-d47t.onrender.com/api/v1/
Local:      http://localhost:8000/api/v1/
```

---

## Authentication

All endpoints require Bearer token authentication.

### Headers Required:
```
Authorization: Bearer <access_token>
Content-Type: application/json
```

### Token Storage (Flutter):
```dart
// Store tokens securely
final prefs = await SharedPreferences.getInstance();
await prefs.setString('access_token', token);

// Include in all API calls
Map<String, String> headers = {
  'Authorization': 'Bearer $accessToken',
  'Content-Type': 'application/json',
};
```

---

## PWA Support

For web deployment, include a manifest.webmanifest:

### manifest.webmanifest
```json
{
  "name": "PCOS Pathfinder",
  "short_name": "PCOS",
  "description": "PCOS Health Assessment & Risk Tracking",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#ffffff",
  "theme_color": "#6366f1",
  "icons": [
    {
      "src": "/icons/icon-192.png",
      "sizes": "192x192",
      "type": "image/png"
    },
    {
      "src": "/icons/icon-512.png",
      "sizes": "512x512",
      "type": "image/png"
    }
  ]
}
```

### Register Service Worker:
```javascript
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js')
      .then(registration => {
        console.log('SW registered:', registration);
      })
      .catch(error => {
        console.log('SW registration failed:', error);
      });
  });
}
```

---

## Core Endpoints

### 1. Comprehensive Prediction

#### GET - Fetch Latest Prediction
```
GET /predictions/comprehensive/
```

**Flutter Implementation:**
```dart
Future<Map<String, dynamic>> getComprehensivePrediction() async {
  final response = await http.get(
    Uri.parse('$BASE_URL/predictions/comprehensive/'),
    headers: headers,
  );
  
  if (response.statusCode == 200) {
    return json.decode(response.body);
  }
  throw Exception('Failed to load prediction');
}
```

**Response Structure:**
```json
{
  "status": "success",
  "data": {
    "id": "uuid-string",
    "final_risk_score": 0.42,
    "risk_tier": "Moderate",
    "pcos_specific_score": 0.45,
    "per_disease_scores": {
      "PCOS": 0.42,
      "CVD": 0.38,
      "T2D": 0.35,
      "Infertility": 0.45,
      "Dysmenorrhea": 0.30,
      "Metabolic": 0.40,
      "MentalHealth": 0.35,
      "Stroke": 0.28,
      "Endometrial": 0.32
    },
    "all_predictions": {
      "symptom": {
        "CVD": {"risk_score": 0.12, "severity": "Minimal"},
        "T2D": {"risk_score": 0.09, "severity": "Minimal"}
      },
      "menstrual": {...},
      "rppg": {...},
      "mood": {...}
    },
    "data_layers_used": ["symptom", "menstrual", "rppg", "mood"],
    "data_completeness_pct": 100,
    "clinical_rules_triggered": ["metabolic_stress"],
    "weights_used": {
      "PCOS": {"symptom": 0.30, "menstrual": 0.35, "rppg": 0.20, "mood": 0.15}
    },
    "highest_risk_disease": "CVD",
    "computed_at": "2026-03-28T00:00:00Z"
  }
}
```

#### POST - Trigger New Prediction
```
POST /predictions/comprehensive/
```

**When to Call:**
- After morning check-in
- After evening check-in
- After period logging
- After rPPG capture
- After mood tracking completion
- Manual refresh by user

**Flutter Implementation:**
```dart
Future<Map<String, dynamic>> triggerComprehensivePrediction() async {
  final response = await http.post(
    Uri.parse('$BASE_URL/predictions/comprehensive/'),
    headers: headers,
  );
  
  if (response.statusCode == 200) {
    return json.decode(response.body);
  }
  throw Exception('Failed to trigger prediction');
}
```

---

## Risk Score Display

### Risk Tier Thresholds

| Tier | Score Range | Color (Hex) |
|------|-------------|-------------|
| Low | 0.00 - 0.24 | #27AE60 (Green) |
| Moderate | 0.25 - 0.49 | #F39C12 (Yellow) |
| High | 0.50 - 0.74 | #E67E22 (Orange) |
| Critical | 0.75 - 1.00 | #E74C3C (Red) |

### Flutter Widget Example:

```dart
class RiskScoreCard extends StatelessWidget {
  final double score;
  final String tier;
  
  Color getTierColor() {
    switch (tier.toLowerCase()) {
      case 'low': return Color(0xFF27AE60);
      case 'moderate': return Color(0xFFF39C12);
      case 'high': return Color(0xFFE67E22);
      case 'critical': return Color(0xFFE74C3C);
      default: return Color(0xFF27AE60);
    }
  }
  
  String getTierLabel() {
    switch (tier.toLowerCase()) {
      case 'low': return 'Low Risk';
      case 'moderate': return 'Moderate Risk';
      case 'high': return 'High Risk';
      case 'critical': return 'Critical Risk';
      default: return tier;
    }
  }
  
  @override
  Widget build(BuildContext context) {
    return Card(
      child: Column(
        children: [
          Text(
            '${(score * 100).toStringAsFixed(0)}%',
            style: TextStyle(
              fontSize: 48,
              fontWeight: FontWeight.bold,
              color: getTierColor(),
            ),
          ),
          Container(
            padding: EdgeInsets.symmetric(horizontal: 12, vertical: 4),
            decoration: BoxDecoration(
              color: getTierColor().withOpacity(0.1),
              borderRadius: BorderRadius.circular(20),
            ),
            child: Text(
              getTierLabel(),
              style: TextStyle(color: getTierColor()),
            ),
          ),
        ],
      ),
    );
  }
}
```

### Per-Disease Scores Display:

```dart
class PerDiseaseScoresWidget extends StatelessWidget {
  final Map<String, double> perDiseaseScores;
  
  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: perDiseaseScores.entries.map((entry) {
        return Padding(
          padding: EdgeInsets.symmetric(vertical: 4),
          child: Row(
            children: [
              SizedBox(width: 100, child: Text(entry.key)),
              Expanded(
                child: LinearProgressIndicator(
                  value: entry.value,
                  backgroundColor: Colors.grey[200],
                  valueColor: AlwaysStoppedAnimation(
                    _getColorForScore(entry.value),
                  ),
                ),
              ),
              SizedBox(width: 40, child: Text('${(entry.value * 100).toStringAsFixed(0)}%')),
            ],
          ),
        );
      }).toList(),
    );
  }
}
```

---

## Escalation System

Escalations notify healthcare providers when risk levels are elevated.

### When to Call Each Endpoint:

| User Action | Endpoint to Call |
|------------|-----------------|
| Weekly tools completed | `/predictions/escalate/mood/` |
| Period logged | `/predictions/escalate/menstrual/` |
| rPPG captured | `/predictions/escalate/rppg/` |

### Severity Thresholds for Escalation:

| Severity | PHC Notified | FMC Notified |
|----------|--------------|--------------|
| Minimal | No | No |
| Mild | No | No |
| Moderate | **Yes** | No |
| Severe | **Yes** | **Yes** |
| Extreme | **Yes** | **Yes** |

### 1. Mood Escalation

```
POST /predictions/escalate/mood/
```

**Flutter Implementation:**
```dart
Future<void> escalateMood(List<Map<String, dynamic>> predictions) async {
  final response = await http.post(
    Uri.parse('$BASE_URL/predictions/escalate/mood/'),
    headers: headers,
    body: json.encode({
      'predictions': predictions,
    }),
  );
  
  if (response.statusCode != 200) {
    throw Exception('Failed to escalate mood');
  }
}
```

**Example Body:**
```json
{
  "predictions": {
    "Anxiety": {"risk_score": 0.47, "severity": "Moderate"},
    "Depression": {"risk_score": 0.40, "severity": "Mild"},
    "ChronicStress": {"risk_score": 0.35, "severity": "Mild"}
  }
}
```

### 2. Menstrual Escalation

```
POST /predictions/escalate/menstrual/
```

**Flutter Implementation:**
```dart
Future<void> escalateMenstrual(
  Map<String, dynamic> predictions,
  Map<String, bool> criterionFlags,
) async {
  final response = await http.post(
    Uri.parse('$BASE_URL/predictions/escalate/menstrual/'),
    headers: headers,
    body: json.encode({
      'predictions': predictions,
      'criterion_flags': criterionFlags,
    }),
  );
}
```

**Example Body:**
```json
{
  "predictions": {
    "Infertility": {"risk_score": 0.61, "severity": "Severe"},
    "Dysmenorrhea": {"risk_score": 0.38, "severity": "Mild"},
    "Endometrial": {"risk_score": 0.53, "severity": "Moderate"}
  },
  "criterion_flags": {
    "oligomenorrhea": true,
    "hyperandrogenism": false
  }
}
```

### 3. rPPG Escalation

```
POST /predictions/escalate/rppg/
```

**Flutter Implementation:**
```dart
Future<void> escalateRppg(Map<String, dynamic> predictions) async {
  final response = await http.post(
    Uri.parse('$BASE_URL/predictions/escalate/rppg/'),
    headers: headers,
    body: json.encode({
      'predictions': predictions,
    }),
  );
}
```

**Example Body:**
```json
{
  "predictions": {
    "CVD": {"risk_score": 0.63, "severity": "High"},
    "Metabolic": {"risk_score": 0.62, "severity": "High"},
    "Stress": {"risk_score": 0.53, "severity": "Moderate"}
  }
}
```

---

## rPPG/HRV Capture

### 1. Log rPPG Session

```
POST /rppg/sessions/
```

**Flutter Implementation:**
```dart
Future<void> logRppgSession({
  required double rmssd,
  required double meanHeartRate,
  required String sessionType,
  int durationSeconds = 30,
}) async {
  final response = await http.post(
    Uri.parse('$BASE_URL/rppg/sessions/'),
    headers: headers,
    body: json.encode({
      'rmssd': rmssd,
      'mean_temp': meanHeartRate,
      'session_type': sessionType,
      'duration_seconds': durationSeconds,
    }),
  );
  
  if (response.statusCode != 201) {
    throw Exception('Failed to log rPPG session');
  }
}
```

### 2. Get rPPG Predictions

```
POST /rppg/predict/metabolic-cardio/
POST /rppg/predict/stress-reproductive/
```

**Flutter Implementation:**
```dart
Future<Map<String, dynamic>> predictMetabolicCardio() async {
  final response = await http.post(
    Uri.parse('$BASE_URL/rppg/predict/metabolic-cardio/'),
    headers: headers,
  );
  return json.decode(response.body);
}

Future<Map<String, dynamic>> predictStressReproductive() async {
  final response = await http.post(
    Uri.parse('$BASE_URL/rppg/predict/stress-reproductive/'),
    headers: headers,
  );
  return json.decode(response.body);
}
```

### rPPG Capture Flow:

```dart
class RppgCaptureScreen extends StatefulWidget {
  @override
  _RppgCaptureScreenState createState() => _RppgCaptureScreenState();
}

class _RppgCaptureScreenState extends State<_RppgCaptureScreen> {
  bool isCapturing = false;
  Map<String, dynamic>? results;
  
  Future<void> startCapture() async {
    setState(() => isCapturing = true);
    
    // Start camera and capture HRV data
    final hrvData = await _captureHRV();
    
    // Log session
    await logRppgSession(
      rmssd: hrvData['rmssd'],
      meanHeartRate: hrvData['mean_heart_rate'],
      sessionType: 'checkin',
    );
    
    // Get predictions
    final metabolicCardio = await predictMetabolicCardio();
    final stressReproductive = await predictStressReproductive();
    
    // Combine predictions
    final predictions = {
      ...metabolicCardio['predictions'],
      ...stressReproductive['predictions'],
    };
    
    // Escalate if needed
    await escalateRppg(predictions);
    
    // Trigger comprehensive
    await triggerComprehensivePrediction();
    
    setState(() {
      isCapturing = false;
      results = hrvData;
    });
  }
  
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: isCapturing
          ? CircularProgressIndicator()
          : ElevatedButton(
              onPressed: startCapture,
              child: Text('Start Capture'),
            ),
      ),
    );
  }
}
```

---

## Dashboard HRV Re-capture

Users can re-capture HRV from the dashboard anytime.

### Dashboard Route
```
/rppg-capture
```

### Flutter Implementation - Dashboard Button:
```dart
class DashboardScreen extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Column(
        children: [
          // Quick action buttons
          ElevatedButton.icon(
            onPressed: () => Navigator.pushNamed(context, '/rppg-capture'),
            icon: Icon(Icons.favorite),
            label: Text('Measure HRV'),
          ),
        ],
      ),
    );
  }
}
```

### Standalone rPPG Capture Screen:
```dart
class RppgCaptureScreen extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('HRV Capture')),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.favorite, size: 80, color: Colors.red),
            SizedBox(height: 24),
            Text('Place your finger on camera'),
            SizedBox(height: 16),
            ElevatedButton(
              onPressed: () => _startCapture(context),
              child: Text('Start Capture'),
            ),
          ],
        ),
      ),
    );
  }
  
  Future<void> _startCapture(BuildContext context) async {
    // 1. Start camera capture
    final hrvData = await _captureHRVFromCamera();
    
    // 2. Log session
    await logRppgSession(
      rmssd: hrvData['rmssd'],
      meanHeartRate: hrvData['mean_heart_rate'],
      sessionType: 'dashboard_recapture',
    );
    
    // 3. Get predictions
    final metabolicCardio = await predictMetabolicCardio();
    final stressReproductive = await predictStressReproductive();
    
    // 4. Combine and escalate
    final predictions = {
      ...metabolicCardio['predictions'],
      ...stressReproductive['predictions'],
    };
    await escalateRppg(predictions);
    
    // 5. Trigger comprehensive
    await triggerComprehensivePrediction();
    
    // 6. Show results
    if (context.mounted) {
      Navigator.pop(context);
      _showResults(context, hrvData, predictions);
    }
  }
}
```

---

## Notifications

### Notification Format

Notifications now include specific disease names:

| Notification Type | Example Message |
|------------------|-----------------|
| PCOS Risk | "Patient alert: Moderate PCOS (Infertility)" |
| CVD Risk | "Patient alert: High CVD" |
| T2D Risk | "Patient alert: Severe T2D" |
| Metabolic | "Patient alert: Moderate Metabolic" |

### Get Notifications
```
GET /notifications/
```

**Flutter Implementation:**
```dart
Future<List<Map<String, dynamic>>> getNotifications() async {
  final response = await http.get(
    Uri.parse('$BASE_URL/notifications/'),
    headers: headers,
  );
  
  final data = json.decode(response.body);
  return data['results'] ?? data['data'];
}
```

**Response:**
```json
{
  "results": [
    {
      "id": "uuid",
      "title": "Patient alert: Moderate PCOS (Infertility)",
      "body": "Registered patient John Doe has Moderate PCOS (Infertility) risk (55/100). Review recommended.",
      "notification_type": "risk_update",
      "priority": "medium",
      "data": {
        "patient_id": "patient-uuid",
        "patient_name": "John Doe",
        "patient_email": "john@example.com",
        "condition": "pcos",
        "severity": "moderate",
        "score": 55,
        "disease": "Infertility",
        "action": "open_patient_risk_report",
        "record_id": "record-uuid"
      },
      "patient_id": "patient-uuid",
      "is_read": false,
      "read_at": null,
      "created_at": "2026-03-28T00:00:00Z"
    }
  ],
  "unread_count": 5
}
```

**Notification Data Fields:**

| Field | Description | Example |
|-------|-------------|---------|
| `patient_id` | ID of the patient this notification is about | `"uuid-string"` |
| `patient_name` | Full name of the patient | `"John Doe"` |
| `patient_email` | Email of the patient | `"john@example.com"` |
| `condition` | Broad condition category | `"pcos"`, `"cardiovascular"`, `"maternal"` |
| `severity` | Risk severity level | `"mild"`, `"moderate"`, `"severe"`, `"very_severe"` |
| `score` | Risk score (0-100) | `55` |
| `disease` | Specific disease name | `"Infertility"`, `"Endometrial"`, `"CVD"` |
| `action` | Action hint for UI | `"open_patient_risk_report"` |
| `record_id` | PHCPatientRecord ID (if applicable) | `"uuid-string"` |
| `case_id` | PatientCase ID (if severe) | `"uuid-string"` |

### Mark All as Read
```
POST /notifications/mark-all-read/
```

**Flutter Implementation:**
```dart
Future<void> markAllNotificationsRead() async {
  final response = await http.post(
    Uri.parse('$BASE_URL/notifications/mark-all-read/'),
    headers: headers,
  );
  
  if (response.statusCode != 200) {
    throw Exception('Failed to mark notifications as read');
  }
}
```

### Notification Bell Badge
```dart
class NotificationBell extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return FutureBuilder<int>(
      future: _getUnreadCount(),
      builder: (context, snapshot) {
        final count = snapshot.data ?? 0;
        return Stack(
          children: [
            IconButton(
              icon: Icon(Icons.notifications),
              onPressed: () => Navigator.pushNamed(context, '/notifications'),
            ),
            if (count > 0)
              Positioned(
                right: 8,
                top: 8,
                child: Container(
                  padding: EdgeInsets.all(4),
                  decoration: BoxDecoration(
                    color: Colors.red,
                    shape: BoxShape.circle,
                  ),
                  child: Text(
                    count > 99 ? '99+' : count.toString(),
                    style: TextStyle(
                      color: Colors.white,
                      fontSize: 10,
                    ),
                  ),
                ),
              ),
          ],
        );
      },
    );
  }
}
```

### Notification Panel with Mark All:
```dart
class NotificationPanel extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('Notifications'),
        actions: [
          TextButton(
            onPressed: () => _markAllRead(context),
            child: Text('Mark All Read'),
          ),
        ],
      ),
      body: ListView.builder(
        itemCount: notifications.length,
        itemBuilder: (context, index) {
          final notification = notifications[index];
          return ListTile(
            leading: Icon(_getIcon(notification['notification_type'])),
            title: Text(notification['title']),
            subtitle: Text(notification['body'] ?? notification['message']),
            trailing: notification['is_read'] 
                ? null 
                : Container(
                    width: 8,
                    height: 8,
                    decoration: BoxDecoration(
                      color: Colors.blue,
                      shape: BoxShape.circle,
                    ),
                  ),
            onTap: () => _handleNotificationTap(context, notification),
          );
        },
      ),
    );
  }
}
```

### Notification Click Handling - Route to Patient Detail

When a notification is clicked, extract the `patient_id` from the notification data and navigate to the patient detail page.

**Routes by User Role:**

| Role | Patient Detail Route |
|------|---------------------|
| PHC Staff/Admin | `/phc/patients/:patient_id` |
| FMC Clinician | `/clinician/patient/:patient_id` |
| Patient | `/patient/report` (own report) |

**Flutter Implementation:**
```dart
class NotificationPanel extends StatefulWidget {
  final String userRole; // 'phc', 'fmc', 'patient'
  
  @override
  _NotificationPanelState createState() => _NotificationPanelState();
}

class _NotificationPanelState extends State<NotificationPanel> {
  List<Map<String, dynamic>> _notifications = [];
  
  void _handleNotificationTap(
    BuildContext context, 
    Map<String, dynamic> notification,
  ) async {
    // Mark notification as read
    await markNotificationRead(notification['id']);
    
    // Extract patient_id from notification data
    final data = notification['data'] ?? {};
    final patientId = data['patient_id'] ?? notification['patient_id'];
    
    if (patientId == null) {
      // No patient ID - show generic notification details
      _showNotificationDetails(context, notification);
      return;
    }
    
    // Route based on user role
    switch (widget.userRole) {
      case 'phc':
        Navigator.pushNamed(
          context, 
          '/phc/patients/$patientId',
        );
        break;
      case 'fmc':
        Navigator.pushNamed(
          context, 
          '/clinician/patient/$patientId',
        );
        break;
      case 'patient':
        Navigator.pushNamed(context, '/patient/report');
        break;
      default:
        _showNotificationDetails(context, notification);
    }
  }
  
  void _showNotificationDetails(
    BuildContext context, 
    Map<String, dynamic> notification,
  ) {
    final data = notification['data'] ?? {};
    showModalBottomSheet(
      context: context,
      builder: (context) => Container(
        padding: EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              notification['title'] ?? 'Notification',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            SizedBox(height: 16),
            Text(notification['body'] ?? ''),
            SizedBox(height: 16),
            if (data['severity'] != null)
              Chip(label: Text(data['severity'].toString().toUpperCase())),
            if (data['score'] != null)
              Text('Risk Score: ${data['score']}/100'),
            if (data['disease'] != null)
              Text('Disease: ${data['disease']}'),
            SizedBox(height: 24),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: () => Navigator.pop(context),
                child: Text('Close'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
```

### Mark Single Notification as Read
```
PATCH /notifications/<id>/read/
```

**Flutter Implementation:**
```dart
Future<void> markNotificationRead(String notificationId) async {
  final response = await http.patch(
    Uri.parse('$BASE_URL/notifications/$notificationId/read/'),
    headers: headers,
  );
  
  if (response.statusCode != 200) {
    throw Exception('Failed to mark notification as read');
  }
}
```

---

## Mood Tracking

### Get Mood Predictions

```
GET /mood/predict/mental_health/
GET /mood/predict/metabolic/
GET /mood/predict/cardio_neuro/
GET /mood/predict/reproductive/
```

**Flutter Implementation:**
```dart
Future<Map<String, dynamic>> getMentalHealthPredictions() async {
  final response = await http.get(
    Uri.parse('$BASE_URL/mood/predict/mental_health/'),
    headers: headers,
  );
  return json.decode(response.body);
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "predictions": {
      "Anxiety": {"risk_score": 0.47, "severity": "Moderate"},
      "Depression": {"risk_score": 0.40, "severity": "Mild"},
      "ChronicStress": {"risk_score": 0.35, "severity": "Mild"},
      "PMDD": {"risk_score": 0.15, "severity": "Minimal"}
    }
  }
}
```

### Complete Mood Tracking Flow:

```dart
Future<void> completeMoodTracking() async {
  // 1. Get all mood predictions
  final mentalHealth = await getMentalHealthPredictions();
  final metabolic = await getMetabolicPredictions();
  final cardio = await getCardioNeuroPredictions();
  final reproductive = await getReproductivePredictions();
  
  // 2. Combine all predictions
  final allPredictions = {
    ...mentalHealth['predictions'],
    ...metabolic['predictions'],
    ...cardio['predictions'],
    ...reproductive['predictions'],
  };
  
  // 3. Escalate based on mood predictions
  final moodOnlyPredictions = {
    'Anxiety': mentalHealth['predictions']['Anxiety'],
    'Depression': mentalHealth['predictions']['Depression'],
    'ChronicStress': mentalHealth['predictions']['ChronicStress'],
  };
  await escalateMood(moodOnlyPredictions);
  
  // 4. Trigger comprehensive prediction
  await triggerComprehensivePrediction();
}
```

---

## Menstrual Tracking

### Get Menstrual Predictions

```
POST /menstrual/predict/
```

**Flutter Implementation:**
```dart
Future<Map<String, dynamic>> getMenstrualPredictions() async {
  final response = await http.post(
    Uri.parse('$BASE_URL/menstrual/predict/'),
    headers: headers,
  );
  return json.decode(response.body);
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "predictions": {
      "Infertility": {"risk_score": 0.61, "severity": "Severe"},
      "Dysmenorrhea": {"risk_score": 0.38, "severity": "Mild"},
      "PMDD": {"risk_score": 0.25, "severity": "Mild"},
      "Endometrial": {"risk_score": 0.53, "severity": "Moderate"}
    },
    "criterion_flags": {
      "oligomenorrhea": true,
      "hyperandrogenism": false
    }
  }
}
```

### Complete Period Logging Flow:

```dart
Future<void> completePeriodLogging() async {
  // 1. Log period data (existing endpoint)
  await logPeriodData(...);
  
  // 2. Get predictions
  final result = await getMenstrualPredictions();
  
  // 3. Escalate based on menstrual predictions
  await escalateMenstrual(
    result['predictions'],
    result['criterion_flags'],
  );
  
  // 4. Trigger comprehensive
  await triggerComprehensivePrediction();
}
```

---

## Admin Features (PHC)

### Ensemble Weight Configuration

PHC admins can view and modify risk calculation weights.

#### GET - Get All Weights
```
GET /predictions/ensemble-config/
Authorization: Bearer <admin_token>
```

**Flutter Implementation:**
```dart
Future<List<Map<String, dynamic>>> getEnsembleWeights() async {
  final response = await http.get(
    Uri.parse('$BASE_URL/predictions/ensemble-config/'),
    headers: adminHeaders,
  );
  
  final data = json.decode(response.body);
  return data['data']['configurations'];
}
```

**Response:**
```json
{
  "data": {
    "configurations": [
      {
        "id": "uuid",
        "disease_name": "PCOS",
        "symptom_weight": 0.30,
        "menstrual_weight": 0.35,
        "rppg_weight": 0.20,
        "mood_weight": 0.15,
        "rotterdam_2_criteria_boost": 0.05,
        "rotterdam_3_criteria_boost": 0.10,
        "is_active": true
      },
      ...
    ]
  }
}
```

#### PUT - Update Weight
```
PUT /predictions/ensemble-config/{disease_name}/
Authorization: Bearer <admin_token>
```

**Flutter Implementation:**
```dart
Future<void> updateWeight({
  required String disease,
  required double symptomWeight,
  required double menstrualWeight,
  required double rppgWeight,
  required double moodWeight,
}) async {
  // Validate weights sum to 1.0
  final total = symptomWeight + menstrualWeight + rppgWeight + moodWeight;
  if ((total - 1.0).abs() > 0.01) {
    throw Exception('Weights must sum to 1.0');
  }
  
  final response = await http.put(
    Uri.parse('$BASE_URL/predictions/ensemble-config/$disease/'),
    headers: adminHeaders,
    body: json.encode({
      'symptom_weight': symptomWeight,
      'menstrual_weight': menstrualWeight,
      'rppg_weight': rppgWeight,
      'mood_weight': moodWeight,
    }),
  );
}
```

#### POST - Reset to Defaults
```
POST /predictions/ensemble-config/reset/
Authorization: Bearer <admin_token>
```

### PHC Staff Creation

PHC admins can create new staff members. The response includes a temporary password.

#### POST - Create Staff
```
POST /centers/hcc/staff/
Authorization: Bearer <admin_token>
```

**Flutter Implementation:**
```dart
class StaffCreationDialog extends StatefulWidget {
  @override
  _StaffCreationDialogState createState() => _StaffCreationDialogState();
}

class _StaffCreationDialogState extends State<StaffCreationDialog> {
  String? tempPassword;
  bool isLoading = false;
  
  Future<void> _createStaff(Map<String, dynamic> staffData) async {
    setState(() => isLoading = true);
    
    try {
      final response = await http.post(
        Uri.parse('$BASE_URL/centers/hcc/staff/'),
        headers: adminHeaders,
        body: json.encode(staffData),
      );
      
      if (response.statusCode == 201) {
        final data = json.decode(response.body);
        // Show temp password dialog
        if (mounted) {
          _showTempPasswordDialog(data['temp_password']);
        }
      }
    } finally {
      if (mounted) setState(() => isLoading = false);
    }
  }
  
  void _showTempPasswordDialog(String password) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Staff Created'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('Temporary password (valid for 24 hours):'),
            SizedBox(height: 16),
            Container(
              padding: EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: Colors.grey[200],
                borderRadius: BorderRadius.circular(8),
              ),
              child: SelectableText(
                password,
                style: TextStyle(
                  fontFamily: 'monospace',
                  fontSize: 18,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
            SizedBox(height: 16),
            Text(
              'Please share this password with the staff member securely.',
              style: TextStyle(fontSize: 12, color: Colors.grey),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: Text('Done'),
          ),
        ],
      ),
    );
  }
}
```

### Ensemble Weight Configuration UI (PHC)

```dart
class EnsembleWeightConfigPanel extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return FutureBuilder<List<EnsembleWeightConfig>>(
      future: getEnsembleWeights(),
      builder: (context, snapshot) {
        if (!snapshot.hasData) return CircularProgressIndicator();
        
        return ListView.builder(
          itemCount: snapshot.data!.length,
          itemBuilder: (context, index) {
            final config = snapshot.data![index];
            return Card(
              child: ExpansionTile(
                title: Text(config.diseaseName),
                children: [
                  Padding(
                    padding: EdgeInsets.all(16),
                    child: Column(
                      children: [
                        _WeightSlider(
                          label: 'Symptom',
                          value: config.symptomWeight,
                          onChanged: (v) => _updateWeight(config.diseaseName, 'symptom', v),
                        ),
                        _WeightSlider(
                          label: 'Menstrual',
                          value: config.menstrualWeight,
                          onChanged: (v) => _updateWeight(config.diseaseName, 'menstrual', v),
                        ),
                        _WeightSlider(
                          label: 'rPPG',
                          value: config.rppgWeight,
                          onChanged: (v) => _updateWeight(config.diseaseName, 'rppg', v),
                        ),
                        _WeightSlider(
                          label: 'Mood',
                          value: config.moodWeight,
                          onChanged: (v) => _updateWeight(config.diseaseName, 'mood', v),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            );
          },
        );
      },
    );
  }
}

class _WeightSlider extends StatelessWidget {
  final String label;
  final double value;
  final Function(double) onChanged;
  
  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        SizedBox(width: 100, child: Text(label)),
        Expanded(
          child: Slider(
            value: value,
            min: 0,
            max: 1,
            divisions: 20,
            onChanged: onChanged,
          ),
        ),
        SizedBox(width: 50, child: Text('${(value * 100).toInt()}%')),
      ],
    );
  }
}
```

---

## Data Models

### ComprehensivePrediction (Flutter):
```dart
class ComprehensivePrediction {
  final String id;
  final double finalRiskScore;
  final String riskTier;
  final double? pcosSpecificScore;
  final Map<String, double> perDiseaseScores;
  final Map<String, Map<String, dynamic>> allPredictions;
  final List<String> dataLayersUsed;
  final int dataCompletenessPct;
  final List<String> clinicalRulesTriggered;
  final Map<String, Map<String, double>> weightsUsed;
  final DateTime computedAt;
  
  factory ComprehensivePrediction.fromJson(Map<String, dynamic> json) {
    return ComprehensivePrediction(
      id: json['id'],
      finalRiskScore: (json['final_risk_score'] as num).toDouble(),
      riskTier: json['risk_tier'],
      pcosSpecificScore: json['pcos_specific_score'] != null
          ? (json['pcos_specific_score'] as num).toDouble()
          : null,
      perDiseaseScores: Map<String, double>.from(
        (json['per_disease_scores'] as Map).map(
          (k, v) => MapEntry(k, (v as num).toDouble()),
        ),
      ),
      // ... parse remaining fields
    );
  }
}
```

### DiseasePrediction (Flutter):
```dart
class DiseasePrediction {
  final double riskScore;
  final String severity;
  
  factory DiseasePrediction.fromJson(Map<String, dynamic> json) {
    return DiseasePrediction(
      riskScore: (json['risk_score'] as num).toDouble(),
      severity: json['severity'],
    );
  }
}
```

### EnsembleWeightConfig (Flutter):
```dart
class EnsembleWeightConfig {
  final String diseaseName;
  final double symptomWeight;
  final double menstrualWeight;
  final double rppgWeight;
  final double moodWeight;
  
  factory EnsembleWeightConfig.fromJson(Map<String, dynamic> json) {
    return EnsembleWeightConfig(
      diseaseName: json['disease_name'],
      symptomWeight: (json['symptom_weight'] as num).toDouble(),
      menstrualWeight: (json['menstrual_weight'] as num).toDouble(),
      rppgWeight: (json['rppg_weight'] as num).toDouble(),
      moodWeight: (json['mood_weight'] as num).toDouble(),
    );
  }
}
```

---

## Error Handling

### Common Error Codes:

```dart
class ApiException implements Exception {
  final int statusCode;
  final String message;
  
  ApiException(this.statusCode, this.message);
  
  @override
  String toString() => 'ApiException: $statusCode - $message';
}

Future<T> safeApiCall<T>(Future<http.Response> Function() request) async {
  try {
    final response = await request();
    
    if (response.statusCode >= 200 && response.statusCode < 300) {
      return json.decode(response.body);
    }
    
    if (response.statusCode == 401) {
      // Token expired, redirect to login
      throw ApiException(401, 'Unauthorized - please login again');
    }
    
    if (response.statusCode == 404) {
      throw ApiException(404, 'Resource not found');
    }
    
    if (response.statusCode >= 500) {
      throw ApiException(500, 'Server error - please try again later');
    }
    
    final body = json.decode(response.body);
    throw ApiException(response.statusCode, body['message'] ?? 'Unknown error');
    
  } on SocketException {
    throw ApiException(0, 'No internet connection');
  } catch (e) {
    if (e is ApiException) rethrow;
    throw ApiException(0, e.toString());
  }
}
```

### Usage:
```dart
try {
  final result = await safeApiCall(() => getComprehensivePrediction());
  // Handle success
} on ApiException catch (e) {
  // Handle error
  showSnackBar(context, e.message);
}
```

---

## Implementation Checklist

### Must Implement:

- [ ] Token storage (SharedPreferences or flutter_secure_storage)
- [ ] API client with headers
- [ ] GET /predictions/comprehensive/
- [ ] POST /predictions/comprehensive/
- [ ] POST /predictions/escalate/mood/
- [ ] POST /predictions/escalate/menstrual/
- [ ] POST /predictions/escalate/rppg/
- [ ] Risk score display with gauge/progress
- [ ] Per-disease scores display
- [ ] Error handling

### Should Implement:

- [ ] rPPG camera capture integration
- [ ] Mood prediction display
- [ ] Menstrual prediction display
- [ ] Data completeness indicator
- [ ] Clinical rules display
- [ ] Dashboard HRV re-capture button
- [ ] Standalone rPPG capture screen

### Nice to Have:

- [ ] Admin ensemble weight configuration (PHC app only)
- [ ] Push notifications for escalations
- [ ] Offline mode with sync
- [ ] Historical trend charts
- [ ] PWA manifest and service worker
- [ ] Temp password dialog for staff creation

---

## API Quick Reference

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/predictions/comprehensive/` | GET | Patient | Get latest prediction |
| `/predictions/comprehensive/` | POST | Patient | Trigger new prediction |
| `/predictions/escalate/mood/` | POST | Patient | Escalate mood risks |
| `/predictions/escalate/menstrual/` | POST | Patient | Escalate menstrual risks |
| `/predictions/escalate/rppg/` | POST | Patient | Escalate rPPG risks |
| `/rppg/sessions/` | POST | Patient | Log rPPG session |
| `/rppg/predict/metabolic-cardio/` | POST | Patient | Get metabolic predictions |
| `/rppg/predict/stress-reproductive/` | POST | Patient | Get stress predictions |
| `/mood/predict/mental_health/` | GET | Patient | Get mental health predictions |
| `/menstrual/predict/` | POST | Patient | Get menstrual predictions |
| `/predictions/ensemble-config/` | GET | Admin | Get weight configs |
| `/predictions/ensemble-config/<disease>/` | PUT | Admin | Update weight |
| `/predictions/ensemble-config/reset/` | POST | Admin | Reset weights |
| `/notifications/` | GET | Both | Get notifications |
| `/notifications/unread-count/` | GET | Both | Get unread count |
| `/notifications/<id>/read/` | PATCH | Both | Mark single as read |
| `/notifications/mark-all-read/` | PATCH | Both | Mark all as read |
| `/centers/hcc/staff/` | POST | Admin | Create staff member |

---

## Support

For questions or issues, contact:
- Backend Developer
- Product Manager

---

*Document Version: 1.2*
*Last Updated: March 28, 2026*
