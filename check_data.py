import requests

r = requests.post(
    "https://ai-mshm-backend-d47t.onrender.com/api/v1/auth/login/",
    json={"email": "owoadeshefiq12@gmail.com", "password": "shefiq1234"},
    timeout=60
)
token = r.json()["data"]["access"]
headers = {"Authorization": f"Bearer {token}"}

# Try with date range
r = requests.get(
    "https://ai-mshm-backend-d47t.onrender.com/api/v1/symptom-intensity/summary/",
    params={"start_date": "2026-03-07", "end_date": "2026-03-20", "page_size": 50},
    headers=headers,
    timeout=60
)
print(f"Status: {r.status_code}")
import json
data = r.json()
print(f"Count: {data.get('meta', {}).get('count', 'no meta')}")
print(json.dumps(data, indent=2)[:1000])