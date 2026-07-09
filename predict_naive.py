import psycopg2

conn = psycopg2.connect(
    host="localhost",
    port=5432,
    dbname="fpl",
    user="postgres",
    password="devpassword"
)
cur = conn.cursor()

cur.execute("ALTER TABLE players ADD COLUMN IF NOT EXISTS predicted_points_next_gw NUMERIC")

cur.execute("SELECT player_id, points_per_game, status, chance_of_playing_next_round FROM players")
rows = cur.fetchall()

for player_id, points_per_game, status, chance_of_playing in rows:
    if status != "a":
        prediction = 0
    elif chance_of_playing is not None and chance_of_playing < 75:
        prediction = float(points_per_game) * (chance_of_playing / 100)
    else:
        prediction = float(points_per_game)

    cur.execute(
        "UPDATE players SET predicted_points_next_gw = %s WHERE player_id = %s",
        (prediction, player_id)
    )

conn.commit()
cur.close()
conn.close()

print("Naive predictions computed and saved.")