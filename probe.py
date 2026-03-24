import requests
import json

BASE = "https://ai-mshm-backend-d47t.onrender.com/api/v1"

r = requests.post(f"{BASE}/auth/login/",
    json={"email": "owoadeshefiq12@gmail.com", "password": "shefiq1234"},
    timeout=60)
token = r.json()["data"]["access"]
headers = {"Authorization": f"Bearer {token}"}
print(f"✓ Logged in\n")

# 1. Check today's state
r = requests.get(f"{BASE}/checkin/today/", headers=headers, timeout=20)
print(f"GET /checkin/today/ → {r.status_code}")
print(json.dumps(r.json(), indent=2)[:800])
print()

# 2. Try starting a session
r = requests.post(f"{BASE}/checkin/session/start/",
    headers=headers,
    json={"period": "morning"},
    timeout=20)
print(f"POST /checkin/session/start/ (morning) → {r.status_code}")
print(r.text[:400])
print()

# 3. Check morning endpoint
r = requests.get(f"{BASE}/checkin/morning/test-id/", headers=headers, timeout=20)
print(f"GET /checkin/morning/test-id/ → {r.status_code}: {r.text[:200]}")
print()

# 4. Try symptom-intensity
for path in ["/symptom-intensity/summary/", "/symptom-intensity/"]:
    r = requests.get(f"{BASE}{path}", headers=headers, timeout=20)
    print(f"GET {path} → {r.status_code}: {r.text[:150]}")