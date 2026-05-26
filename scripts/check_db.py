import psycopg2
conn = psycopg2.connect(dbname='battery_finder_dev', user='brandon', password='6419', host='localhost', port=5432)
cur = conn.cursor()
cur.execute('SELECT id, satisfaction, match_type, match_confidence, input_type, comments, accuracy FROM user_feedback ORDER BY submitted_at DESC')
for r in cur.fetchall():
    print(r)
cur.close()
conn.close()
