import psycopg2

conn = psycopg2.connect('postgresql://postgres:admin@localhost:5432/Kenta')
cur = conn.cursor()

# Check news_raw columns
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'news_raw' AND table_schema = 'raw'")
print('news_raw columns:', [r[0] for r in cur.fetchall()])

# Check news_processed columns
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'news_processed' AND table_schema = 'processed'")
print('news_processed columns:', [r[0] for r in cur.fetchall()])

cur.close()
conn.close()