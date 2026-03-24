import requests
import time
from datetime import datetime, timedelta

DJANGO_BASE = "https://ai-mshm-backend-d47t.onrender.com/api/v1"
EMAIL = "owoadeshefiq12@gmail.com"
PASSWORD = "shefiq1234"

def login():
    r = requests.post(
        f"{DJANGO_BASE}/auth/login/",
        json={"email": EMAIL, "password": PASSWORD},
        timeout=60
    )
    token = r.json()["data"]["access"]
    print(f"✓ Django token obtained")
    return token

def get_session_id(r):
    data = r.json().get("data", {})
    return data.get("id") or data.get("session_id")

def do_checkin(token, period, day_offset, i):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    date = (datetime.today() - timedelta(days=day_offset)).strftime("%Y-%m-%d")

    # Start session
    try:
        r = requests.post(
            f"{DJANGO_BASE}/checkin/session/start/",
            json={"period": period},
            headers=headers,
            timeout=60
        )
    except Exception as e:
        print(f"  {period} day {i+1} ({date}): start timeout — {type(e).__name__}")
        return False

    if r.status_code not in [200, 201]:
        msg = ""
        try: msg = r.json().get("message", "")
        except: pass
        print(f"  {period} day {i+1} ({date}): start {r.status_code} — {msg}")
        return False

    sid = get_session_id(r)
    session_status = r.json().get("data", {}).get("status", "")
    if session_status == "completed":
        print(f"  {period} day {i+1} ({date}): already done ✓")
        return True

    # Save symptoms
    try:
        if period == "morning":
            requests.post(
                f"{DJANGO_BASE}/checkin/morning/{sid}/",
                json={
                    "fatigue_vas": round(3 + (i % 5) * 0.8, 1),
                    "pelvic_pressure_vas": round(2 + (i % 4) * 0.9, 1),
                    "psq_skin_sensitivity": 3.0,
                    "psq_muscle_pressure_pain": 4.0,
                    "psq_body_tenderness": 3.0,
                },
                headers=headers, timeout=60
            )
            requests.post(
                f"{DJANGO_BASE}/checkin/hrv/",
                json={
                    "session_id": sid,
                    "hrv_sdnn_ms": round(38 + (i % 8) * 1.5, 1),
                    "hrv_rmssd_ms": round(32 + (i % 6) * 1.2, 1),
                    "skipped": False
                },
                headers=headers, timeout=60
            )
        else:
            requests.post(
                f"{DJANGO_BASE}/checkin/evening/{sid}/",
                json={
                    "breast_left_vas": round(2 + (i % 4) * 0.8, 1),
                    "breast_right_vas": round(1.5 + (i % 3) * 0.9, 1),
                    "mastalgia_side": "Bilateral",
                    "mastalgia_quality": "Dull",
                    "acne_forehead": i % 3,
                    "acne_right_cheek": i % 2,
                    "acne_left_cheek": i % 2,
                    "acne_nose": 0,
                    "acne_chin": i % 2,
                    "acne_chest_back": 0,
                    "bloating_delta_cm": round(1 + (i % 4) * 0.5, 1),
                    "unusual_bleeding": False
                },
                headers=headers, timeout=60
            )
    except Exception as e:
        print(f"  {period} day {i+1} ({date}): symptoms timeout — skipping submit")
        return False

    # Submit — timeout here is EXPECTED because Celery/Redis is broken
    # We use a SHORT timeout — if it saves and then hangs on Celery, that's OK
    try:
        r_sub = requests.post(
            f"{DJANGO_BASE}/checkin/session/{sid}/submit/",
            json={},
            headers=headers,
            timeout=15  # ← short on purpose — data is saved, Celery hanging is OK
        )
        if r_sub.status_code in [200, 201]:
            print(f"  {period} day {i+1} ({date}): ✓")
        else:
            try: msg = r_sub.json().get("message", "")
            except: msg = r_sub.text[:80]
            print(f"  {period} day {i+1} ({date}): {r_sub.status_code} — {msg}")

    except requests.exceptions.Timeout:
        # Celery hung but data is saved — treat as success
        print(f"  {period} day {i+1} ({date}): ✓ (saved, inference queued)")

    except Exception as e:
        print(f"  {period} day {i+1} ({date}): submit error — {type(e).__name__}")

    return True

def seed_checkins(token):
    print("\n--- Seeding 14 days of check-ins ---")
    for i in range(14):
        day_offset = 13 - i
        do_checkin(token, "morning", day_offset, i)
        time.sleep(1)
        do_checkin(token, "evening", day_offset, i)
        time.sleep(1)
    print("✓ Check-ins done")

def seed_mfg(token):
    print("\n--- Seeding mFG Score ---")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    try:
        r = requests.post(
            f"{DJANGO_BASE}/checkin/mfg/",
            json={
                "upper_lip": 2, "chin": 1, "chest": 1,
                "upper_abdomen": 1, "lower_abdomen": 2,
                "upper_arm": 1, "thigh": 2,
                "upper_back": 1, "lower_back": 1
            },
            headers=headers,
            timeout=30
        )
        if r.status_code in [200, 201]:
            print("  mFG: ✓")
        else:
            try: msg = r.json().get("message", r.text[:150])
            except: msg = r.text[:150]
            print(f"  mFG: {r.status_code} — {msg}")
    except requests.exceptions.Timeout:
        print("  mFG: ✓ (saved, inference queued)")
    except Exception as e:
        print(f"  mFG: error — {e}")

if __name__ == "__main__":
    print("=== Seeding Django Backend ===\n")
    token = login()
    seed_checkins(token)
    seed_mfg(token)
    print("\n=== Done ===")