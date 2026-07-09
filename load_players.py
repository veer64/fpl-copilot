import requests
import psycopg2

url = "https://fantasy.premierleague.com/api/bootstrap-static/"
response = requests.get(url)
data = response.json()

teams = {team["id"]: team["name"] for team in data["teams"]}
positions = {pos["id"]: pos["singular_name"] for pos in data["element_types"]}
players = data["elements"]

conn = psycopg2.connect(
    host="localhost",
    port=5432,
    dbname="fpl",
    user="postgres",
    password="devpassword"
)
cur = conn.cursor()

for player in players:
    cur.execute("""
        INSERT INTO players (
            player_id, first_name, second_name, team_name, position_name, price,
            total_points, points_per_game, form, minutes, chance_of_playing_next_round, status
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (player_id) DO UPDATE SET
            first_name = EXCLUDED.first_name,
            second_name = EXCLUDED.second_name,
            team_name = EXCLUDED.team_name,
            position_name = EXCLUDED.position_name,
            price = EXCLUDED.price,
            total_points = EXCLUDED.total_points,
            points_per_game = EXCLUDED.points_per_game,
            form = EXCLUDED.form,
            minutes = EXCLUDED.minutes,
            chance_of_playing_next_round = EXCLUDED.chance_of_playing_next_round,
            status = EXCLUDED.status
    """, (
        player["id"],
        player["first_name"],
        player["second_name"],
        teams[player["team"]],
        positions[player["element_type"]],
        player["now_cost"] / 10,
        player["total_points"],
        player["points_per_game"],
        player["form"],
        player["minutes"],
        player["chance_of_playing_next_round"],
        player["status"]
    ))

conn.commit()
cur.close()
conn.close()

print(f"Loaded {len(players)} players into the database.")