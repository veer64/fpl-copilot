"""
FPL Copilot — Squad state (the thing that carries between gameweeks)

The optimizer is stateless: it picks the best 15 from scratch, every time. A real
season is not like that. What you did last week constrains this week, and this
module is what remembers.

FOUR THINGS PERSIST
-------------------
1. The 15 players you own — AND what you paid for each. The purchase price is not
   bookkeeping trivia; it is what determines how much you get back when you sell.
2. Bank — money not currently spent on players.
3. Free transfers — one earned per gameweek, banked up to a cap of 5.
4. Points so far — the running total.

THE SELL-PRICE RULE (the reason purchase price is stored)
---------------------------------------------------------
FPL does not give you the current price when you sell. It gives you your purchase
price plus HALF of any rise, rounded down. Falls are taken in full.

    rise:  sell = bought + floor((now - bought) / 2)
    fall:  sell = now

All prices are in tenths of a million (55 = £5.5m), so "half, rounded down" is
integer division on tenths. Worked examples, bought at 120:

    now 124 (rise 4)  -> 120 + 2 = 122
    now 123 (rise 3)  -> 120 + 1 = 121   (floor(1.5) = 1)
    now 117 (fall 3)  -> 117             (you eat the whole loss)

Getting this wrong inflates your budget every single week, compounding across the
season into a squad you could never actually have afforded. In this dataset 600 of
841 players moved price during 2025-26, so it is not a rounding concern.

WHAT THIS MODULE DOES NOT DO
----------------------------
It does not decide anything. No transfer logic, no optimization, no scoring. It
holds state and applies FPL's accounting rules to it. Decisions live in the
simulator; scoring lives in scoring.py.
"""

import pandas as pd

MAX_FREE_TRANSFERS = 5      # free transfers bank up to this many
SQUAD_SIZE = 15
STARTING_BUDGET = 1000      # £100.0m in tenths


def sell_price(purchase_price, current_price):
    """What you actually receive for selling a player.

    Rises are shared with FPL (you get half, rounded down); falls are yours alone.
    Both prices in tenths of a million.
    """
    if current_price <= purchase_price:
        return current_price                      # full loss on a fall
    rise = current_price - purchase_price
    return purchase_price + rise // 2             # half the rise, rounded down


class SquadState:
    """The 15 players, what they cost, the bank, and free transfers.

    Deliberately a plain object with explicit methods rather than a bag of
    dictionaries: the season loop mutates this every gameweek, and a typo in a
    dict key would fail silently where a missing method fails loudly.
    """

    def __init__(self, squad, bank=0, free_transfers=1, total_points=0):
        """squad: DataFrame with element, position, purchase_price (at minimum).
        Any other columns (name, team) are carried along untouched."""
        if len(squad) != SQUAD_SIZE:
            raise ValueError(f"squad has {len(squad)} players, must be {SQUAD_SIZE}")
        if "purchase_price" not in squad.columns:
            raise ValueError("squad must carry purchase_price — see the sell-price rule")

        self.squad = squad.reset_index(drop=True).copy()
        self.bank = int(bank)
        self.free_transfers = int(free_transfers)
        self.total_points = int(total_points)

    # -- money ---------------------------------------------------------------

    def sell_value(self, prices):
        """Total you would receive for selling all 15 right now.

        prices: dict {element: current_price in tenths}. A player missing from
        `prices` is valued at what you paid — the safe reading when a player has
        no row this gameweek, since assuming a rise would invent money.
        """
        total = 0
        for _, r in self.squad.iterrows():
            bought = int(r["purchase_price"])
            now = int(prices.get(r["element"], bought))
            total += sell_price(bought, now)
        return total

    def budget(self, prices):
        """Everything you could spend if you sold the whole squad: sell value
        plus whatever is already in the bank."""
        return self.sell_value(prices) + self.bank

    def element_sell_price(self, element, prices):
        """What one specific player would fetch."""
        row = self.squad[self.squad["element"] == element]
        if len(row) == 0:
            raise ValueError(f"element {element} is not in this squad")
        bought = int(row.iloc[0]["purchase_price"])
        return sell_price(bought, int(prices.get(element, bought)))

    # -- transfers -----------------------------------------------------------

    def make_transfer(self, out_element, in_element, in_row, prices):
        """Swap one player for another, updating the bank correctly.

        in_row : a Series/dict for the incoming player with at least element,
                 position, and value (his CURRENT price — what you pay).
        prices : {element: current price}, used to value the outgoing player.

        The incoming player's purchase_price is set to what you paid right now,
        which is what makes future sell-price maths correct.

        Raises if the transfer is unaffordable, rather than silently going
        overdrawn — a negative bank would quietly corrupt the whole season.
        """
        if out_element == in_element:
            raise ValueError("cannot transfer a player for himself")
        if out_element not in set(self.squad["element"]):
            raise ValueError(f"element {out_element} is not in this squad")
        if in_element in set(self.squad["element"]):
            raise ValueError(f"element {in_element} is already in this squad")

        received = self.element_sell_price(out_element, prices)
        paid = int(in_row["value"])
        new_bank = self.bank + received - paid
        if new_bank < 0:
            raise ValueError(
                f"transfer unaffordable: bank {self.bank} + {received} - {paid} "
                f"= {new_bank}"
            )

        out_pos = self.squad.loc[self.squad["element"] == out_element, "position"].iloc[0]
        if in_row["position"] != out_pos:
            raise ValueError(
                f"position mismatch: selling a {out_pos}, buying a {in_row['position']}. "
                "The 15 is fixed at 2 GK / 5 DEF / 5 MID / 3 FWD."
            )

        keep = self.squad[self.squad["element"] != out_element]
        incoming = {c: in_row[c] for c in self.squad.columns if c in in_row}
        incoming["element"] = in_element
        incoming["position"] = in_row["position"]
        incoming["purchase_price"] = paid

        self.squad = pd.concat(
            [keep, pd.DataFrame([incoming])], ignore_index=True
        )
        self.bank = new_bank

    def spend_transfers(self, n):
        """Account for n transfers made this gameweek.

        Returns the number of PAID transfers (each costing 4 points). Free
        transfers are consumed first; anything beyond them is a hit.
        """
        paid = max(0, n - self.free_transfers)
        self.free_transfers = max(0, self.free_transfers - n)
        return paid

    def end_gameweek(self, points_scored):
        """Roll the state forward: bank the points, earn next week's transfer."""
        self.total_points += int(points_scored)
        self.free_transfers = min(MAX_FREE_TRANSFERS, self.free_transfers + 1)

    # -- convenience ---------------------------------------------------------

    @property
    def elements(self):
        return list(self.squad["element"])

    def to_dict(self):
        """A snapshot for the decision log. Everything needed to reconstruct
        this gameweek's position after the fact."""
        return {
            "elements": self.elements,
            "purchase_prices": dict(zip(self.squad["element"],
                                        self.squad["purchase_price"])),
            "bank": self.bank,
            "free_transfers": self.free_transfers,
            "total_points": self.total_points,
        }

    def __repr__(self):
        return (f"SquadState(15 players, bank={self.bank}, "
                f"ft={self.free_transfers}, pts={self.total_points})")


def initial_squad_from_team(team, prices=None):
    """Turn an optimizer `get_team()` result into a starting SquadState.

    At gameweek 1 there is no history, so purchase_price is simply the price you
    paid — the `value` column from the optimizer input.
    """
    s = team.copy()
    s["purchase_price"] = s["value"].astype(int)
    spent = int(s["purchase_price"].sum())
    return SquadState(s, bank=STARTING_BUDGET - spent, free_transfers=1)