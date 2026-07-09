import psycopg2

conn = psycopg2.connect(
    host="localhost",
    port=5432,
    dbname="fpl",
    user="postgres",
    password="devpassword"
)
cur = conn.cursor()

cur.execute("""
    CREATE TABLE IF NOT EXISTS players (
        player_id INTEGER PRIMARY KEY,
        first_name TEXT,
        second_name TEXT,
        team_name TEXT,
        position_name TEXT,
        price NUMERIC
    )
""")

# Add the new columns if they don't already exist
cur.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS total_points INTEGER")
cur.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS points_per_game NUMERIC")
cur.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS form NUMERIC")
cur.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS minutes INTEGER")
cur.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS chance_of_playing_next_round INTEGER")
cur.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS status TEXT")

conn.commit()
cur.close()
conn.close()

print("Table created/updated.")