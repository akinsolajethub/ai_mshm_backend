import psycopg2
from decouple import config

DATABASE_URL = config("DATABASE_URL", "postgresql://localhost:27017")

conn = psycopg2.connect(DATABASE_URL)

cur = conn.cursor()

cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public';")
tables = cur.fetchall()

for table_name, in tables:
    print(f"Dropping table {table_name}...")
    cur.execute(f'DROP TABLE IF EXISTS "{table_name}" CASCADE;')

conn.commit()
cur.close()
conn.close()

print("All tables dropped successfully!")