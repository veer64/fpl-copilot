import psycopg2
import pulp

# 1. Pull player data from the database
conn = psycopg2.connect(
    host="localhost",
    port=5432,
    dbname="fpl",
    user="postgres",
    password="devpassword"
)
cur = conn.cursor()
cur.execute("""
    SELECT player_id, first_name, second_name, team_name, position_name, price, predicted_points_next_gw
    FROM players
    WHERE status = 'a'
""")
rows = cur.fetchall()
cur.close()
conn.close()

# 2. Set up the optimization problem
prob = pulp.LpProblem("FPL_Squad_Selection", pulp.LpMaximize)

# One yes/no decision variable per player: "is this player in the squad?"
player_vars = {
    row[0]: pulp.LpVariable(f"player_{row[0]}", cat="Binary")
    for row in rows
}

# 3. The goal: maximize total predicted points
prob += pulp.lpSum(
    player_vars[row[0]] * float(row[6]) for row in rows
)

# 4. The constraints

# Budget: total price <= 100
prob += pulp.lpSum(
    player_vars[row[0]] * float(row[5]) for row in rows
) <= 100

# Position counts
position_targets = {
    "Goalkeeper": 2,
    "Defender": 5,
    "Midfielder": 5,
    "Forward": 3
}
for position, target in position_targets.items():
    prob += pulp.lpSum(
        player_vars[row[0]] for row in rows if row[4] == position
    ) == target

# Max 3 players per club
teams = set(row[3] for row in rows)
for team in teams:
    prob += pulp.lpSum(
        player_vars[row[0]] for row in rows if row[3] == team
    ) <= 3

# 5. Solve it
prob.solve(pulp.PULP_CBC_CMD(msg=0))

# 6. Print the results
print(f"Status: {pulp.LpStatus[prob.status]}\n")

total_price = 0
total_points = 0
squad = [row for row in rows if player_vars[row[0]].varValue == 1]

for position in ["Goalkeeper", "Defender", "Midfielder", "Forward"]:
    print(f"--- {position} ---")
    for row in squad:
        if row[4] == position:
            player_id, first_name, second_name, team_name, position_name, price, predicted = row
            print(f"{first_name} {second_name} ({team_name}) | £{price}m | predicted: {predicted}")
            total_price += float(price)
            total_points += float(predicted)

print(f"\nTotal cost: £{total_price:.1f}m")
print(f"Total predicted points: {total_points:.1f}")