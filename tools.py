import os
import psycopg2
import pulp
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "fpl"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "devpassword")
    )


def resolve_player(name: str):
    """
    Search for players by partial name match (first or last name).
    Returns a list of candidates so ambiguous names can be disambiguated.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT player_id, first_name, second_name, team_name, position_name
        FROM players
        WHERE first_name ILIKE %s OR second_name ILIKE %s
        LIMIT 5
    """, (f"%{name}%", f"%{name}%"))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    candidates = []
    for player_id, first_name, second_name, team_name, position_name in rows:
        candidates.append({
            "player_id": player_id,
            "name": f"{first_name} {second_name}",
            "team": team_name,
            "position": position_name
        })
    return candidates

def get_player_card(player_id: int):
    """
    Get full details for a single player by ID.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT first_name, second_name, team_name, position_name, price,
               total_points, points_per_game, form, minutes,
               status, chance_of_playing_next_round, predicted_points_next_gw
        FROM players
        WHERE player_id = %s
    """, (player_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if row is None:
        return {"error": f"No player found with id {player_id}"}

    first_name, second_name, team_name, position_name, price, total_points, points_per_game, form, minutes, status, chance_of_playing, predicted = row

    return {
        "name": f"{first_name} {second_name}",
        "team": team_name,
        "position": position_name,
        "price": float(price),
        "total_points_this_season": total_points,
        "points_per_game": float(points_per_game),
        "form": float(form),
        "minutes_played": minutes,
        "status": status,
        "chance_of_playing_next_round": chance_of_playing,
        "predicted_points_next_gw": float(predicted)
    }

def predict_points(player_id: int):
    """
    Get the predicted points for a player's next gameweek.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT first_name, second_name, predicted_points_next_gw, status
        FROM players
        WHERE player_id = %s
    """, (player_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if row is None:
        return {"error": f"No player found with id {player_id}"}

    first_name, second_name, predicted, status = row

    return {
        "name": f"{first_name} {second_name}",
        "predicted_points_next_gw": float(predicted),
        "status": status
    }

def optimize_squad():
    """
    Build the optimal 15-player FPL squad under budget, position, and club constraints.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT player_id, first_name, second_name, team_name, position_name, price, predicted_points_next_gw
        FROM players
        WHERE status = 'a'
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    prob = pulp.LpProblem("FPL_Squad_Selection", pulp.LpMaximize)
    player_vars = {row[0]: pulp.LpVariable(f"player_{row[0]}", cat="Binary") for row in rows}

    prob += pulp.lpSum(player_vars[row[0]] * float(row[6]) for row in rows)
    prob += pulp.lpSum(player_vars[row[0]] * float(row[5]) for row in rows) <= 100

    position_targets = {"Goalkeeper": 2, "Defender": 5, "Midfielder": 5, "Forward": 3}
    for position, target in position_targets.items():
        prob += pulp.lpSum(player_vars[row[0]] for row in rows if row[4] == position) == target

    teams = set(row[3] for row in rows)
    for team in teams:
        prob += pulp.lpSum(player_vars[row[0]] for row in rows if row[3] == team) <= 3

    prob.solve(pulp.PULP_CBC_CMD(msg=0))

    squad = [row for row in rows if player_vars[row[0]].varValue == 1]

    result = {"squad": [], "total_cost": 0, "total_predicted_points": 0}
    for player_id, first_name, second_name, team_name, position_name, price, predicted in squad:
        result["squad"].append({
            "name": f"{first_name} {second_name}",
            "team": team_name,
            "position": position_name,
            "price": float(price),
            "predicted_points": float(predicted)
        })
        result["total_cost"] += float(price)
        result["total_predicted_points"] += float(predicted)

    return result

def list_players(team: str = None, position: str = None):
    """
    List players, optionally filtered by team and/or position.
    Useful for questions like 'who plays for Chelsea' or 'list all defenders'.
    """
    conn = get_connection()
    cur = conn.cursor()

    query = """
        SELECT first_name, second_name, team_name, position_name, price,
               points_per_game, status
        FROM players
        WHERE status = 'a'
    """
    params = []

    if team:
        query += " AND team_name ILIKE %s"
        params.append(f"%{team}%")

    if position:
        query += " AND position_name ILIKE %s"
        params.append(f"%{position}%")

    query += " ORDER BY points_per_game DESC LIMIT 20"

    cur.execute(query, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    players = []
    for first_name, second_name, team_name, position_name, price, points_per_game, status in rows:
        players.append({
            "name": f"{first_name} {second_name}",
            "team": team_name,
            "position": position_name,
            "price": float(price),
            "points_per_game": float(points_per_game)
        })
    return players