import requests
import json

DJANGO_BASE = "https://ai-mshm-backend-d47t.onrender.com/api/v1"

r = requests.post(f"{DJANGO_BASE}/auth/login/",
    json={"email": "owoadeshefiq12@gmail.com", "password": "shefiq1234"},
    timeout=60)
token = r.json()["data"]["access"]
headers = {"Authorization": f"Bearer {token}"}

# Try different endpoints and params
endpoints = [
    "/symptom-intensity/summary/?page_size=50",
    "/symptom-intensity/summary/?start_date=2026-03-01&end_date=2026-03-20&page_size=50",
    "/checkin/history/?page_size=50",
    "/checkin/sessions/?page_size=50",
]

for ep in endpoints:
    try:
        r = requests.get(f"{DJANGO_BASE}{ep}", headers=headers, timeout=30)
        if r.status_code == 200:
            data = r.json()
            count = data.get("meta", {}).get("count", len(data.get("data", [])))
            print(f"✓ {ep} → {r.status_code} — count: {count}")
        else:
            print(f"✗ {ep} → {r.status_code}")
    except Exception as e:
        print(f"✗ {ep} → ERROR: {e}")