# Team-news investigation — step 1: the case list (2026-08-21)

52 squad-gameweeks across three d45 baseline paths where an owned player was predicted >= 60 minutes at his own cutoff and played 0. Built by eval/build_teamnews_cases.py (grouping heuristics in its header); parquet: data/teamnews/case_list.parquet. Steps 2-3 will establish what was publicly reported, against THIS fixed list.

## Group counts

- tactical_bench: 16
- injury_emerging: 15
- rotation_congested: 12
- unclear: 5
- post_break_call: 2
- flagged_at_deadline: 2

## Cases

### 2023-24 (13 cases)

| gw | player | team | e_min | e_pts | cap | asof status/chance/news | mins gw-3..gw+3 | fixture | group |
|---|---|---|---|---|---|---|---|---|---|
| 2 | Nathan Aké | Man City | 72 | 3.4 |  | a/100/ | - - 78 [0] 90 90 1 | weekend, prev 8.0d, next 7.0d | tactical_bench |
| 3 | Alejandro Garnacho | Man Utd | 63 | 6.2 |  | a// | - 67 65 [0] 6 5 0 | weekend, prev 6.0d, next 8.0d | tactical_bench |
| 5 | Aaron Ramsdale | Arsenal | 88 | 4.4 |  | a// | 90 90 90 [0] 0 0 0 | weekend, prev 14.0d, next 6.0d | injury_emerging |
| 5 | Pervis Estupiñán | Brighton | 88 | 3.8 |  | a// | 90 90 90 [0] 90 45 0 | weekend, prev 13.0d, next 7.0d | post_break_call |
| 12 | Benjamin White | Arsenal | 82 | 5.2 |  | a// | 90 65 72 [0] 1 11 90 | weekend, prev 6.0d, next 14.0d | tactical_bench |
| 12 | Levi Colwill | Chelsea | 73 | 2.4 |  | a// | 90 90 45 [0] 15 90 90 | weekend, prev 5.0d, next 12.0d | tactical_bench |
| 15 | Konstantinos Tsimikas | Liverpool | 82 | 5.0 |  | a// | 90 90 90 [0] 90 90 34 | midweek, prev 3.0d, next 2.0d | rotation_congested |
| 16 | Erling Haaland | Man City | 86 | 10.5 | C | a/100/ | 90 90 90 [0] 0 - 0 | weekend, prev 3.0d, next 6.0d | injury_emerging |
| 29 | James Trafford | Burnley | 86 | 3.6 |  | a// | 90 90 90 [0] 0 0 0 | weekend, prev 6.0d, next 14.0d | injury_emerging |
| 31 | Erling Haaland | Man City | 87 | 9.6 | C | a/100/ | 90 - 90 [0] 90 80 0 | midweek, prev 3.0d, next 2.0d | rotation_congested |
| 32 | Malo Gusto | Chelsea | 82 | 4.7 |  | a/75/ | - 86 74 [0] 87 0 0 | weekend, prev 2.0d, next 8.0d | rotation_congested |
| 34 | Malo Gusto | Chelsea | 69 | 2.0 |  | a/100/ | 74 0 87 [0] 0 7 100 | midweek, prev 8.0d, next 4.0d | injury_emerging |
| 35 | Norberto Murara Neto | Bournemouth | 87 | 3.6 |  | a/100/ | 90 90 90 [0] 0 0 90 | weekend, prev 3.0d, next 5.0d | injury_emerging |

### 2024-25 (24 cases)

| gw | player | team | e_min | e_pts | cap | asof status/chance/news | mins gw-3..gw+3 | fixture | group |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Kieran Trippier | Newcastle | 60 | 3.8 |  | a// | - - - [0] 32 0 26 | weekend, prev nand, next 7.0d | tactical_bench |
| 5 | Diogo Teixeira da Silva | Liverpool | 66 | 6.9 |  | a// | 71 75 59 [0] 90 90 29 | weekend, prev 7.0d, next 7.0d | tactical_bench |
| 5 | Kevin De Bruyne | Man City | 76 | 5.2 |  | d//Groin Injury - 75% chance of playing | 89 87 90 [0] 0 0 0 | weekend, prev 8.0d, next 5.0d | flagged_at_deadline |
| 5 | Rico Lewis | Man City | 73 | 3.9 |  | a// | 90 90 45 [0] 80 90 90 | weekend, prev 8.0d, next 5.0d | tactical_bench |
| 8 | Manuel Akanji | Man City | 73 | 3.4 |  | a// | 90 90 61 [0] 90 90 0 | weekend, prev 14.0d, next 6.0d | post_break_call |
| 9 | Lewis Dunk | Brighton | 85 | 3.7 |  | a// | 90 90 90 [0] 0 0 0 | weekend, prev 7.0d, next 7.0d | injury_emerging |
| 11 | Manuel Akanji | Man City | 76 | 2.9 |  | a/75/ | 0 90 90 [0] 90 90 45 | weekend, prev 7.0d, next 14.0d | tactical_bench |
| 13 | Dominic Solanke-Mitchell | Spurs | 83 | 5.6 |  | a/100/ | 90 90 90 [0] 90 90 81 | weekend, prev 7.0d, next 4.0d | rotation_congested |
| 14 | Gabriel dos Santos Magalhães | Arsenal | 61 | 3.8 |  | d/75/Knock - 75% chance of playing | 90 90 45 [0] 0 90 90 | midweek, prev 4.0d, next 3.0d | flagged_at_deadline |
| 14 | Nicolas Jackson | Chelsea | 79 | 6.1 |  | a// | 87 90 70 [0] 75 82 75 | midweek, prev 3.0d, next 3.0d | rotation_congested |
| 19 | Kai Havertz | Arsenal | 72 | 4.8 |  | a/100/ | 90 57 90 [0] 0 90 90 | midweek, prev 4.0d, next 3.0d | injury_emerging |
| 20 | Lewis Dunk | Brighton | 80 | 2.6 |  | a/100/ | 90 90 90 [0] 27 90 90 | weekend, prev 4.0d, next 12.0d | rotation_congested |
| 21 | Rico Lewis | Man City | 78 | 3.9 |  | a/100/ | 90 90 90 [0] 18 0 0 | midweek, prev 10.0d, next 4.0d | rotation_congested |
| 22 | Bernardo Veiga de Carvalho e Silva | Man City | 84 | 4.8 |  | a// | 90 90 90 [0] 90 90 0 | weekend, prev 4.0d, next 6.0d | rotation_congested |
| 22 | Dominic Solanke-Mitchell | Spurs | 85 | 4.1 |  | a/100/ | 90 90 90 [0] 0 0 0 | weekend, prev 3.0d, next 7.0d | injury_emerging |
| 22 | William Saliba | Arsenal | 86 | 4.7 |  | a/100/ | 90 90 90 [0] 90 90 90 | weekend, prev 2.0d, next 6.0d | rotation_congested |
| 24 | Mark Flekken | Brentford | 87 | 4.2 |  | a/100/ | 90 90 90 [0] 90 90 90 | weekend, prev 7.0d, next 13.0d | tactical_bench |
| 25 | Bernardo Veiga de Carvalho e Silva | Man City | 78 | 3.8 |  | a// | 0 90 90 [0] 0 16 90 | weekend, prev 12.0d, next 8.0d | injury_emerging |
| 26 | Lucas Digne | Aston Villa | 68 | 2.9 |  | a// | 90 45 122 [0] 77 90 - | weekend, prev 2.0d, next 3.0d | rotation_congested |
| 28 | Emiliano Martínez Romero | Aston Villa | 84 | 3.5 |  | a/100/ | 180 90 45 [0] - 90 90 | weekend, prev 10.0d, next 25.0d | unclear |
| 29 | Cole Palmer | Chelsea | 84 | 3.8 |  | a/100/ | 90 90 72 [0] 90 31 90 | weekend, prev 6.0d, next 18.0d | tactical_bench |
| 31 | Lucas Digne | Aston Villa | 78 | 3.7 |  | a// | 90 - 90 [0] 0 90 - | weekend, prev 2.0d, next 6.0d | injury_emerging |
| 31 | Sávio 'Savinho' Moreira de Oliveira | Man City | 68 | 3.5 |  | a/100/ | 68 57 84 [0] 8 77 - | weekend, prev 3.0d, next 5.0d | rotation_congested |
| 35 | Luis Díaz | Liverpool | 77 | 4.2 |  | a/100/ | 90 90 75 [0] 78 27 68 | weekend, prev 7.0d, next 7.0d | tactical_bench |

### 2025-26 (15 cases)

| gw | player | team | e_min | e_pts | cap | asof status/chance/news | mins gw-3..gw+3 | fixture | group |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Kyle Walker-Peters | West Ham | 66 | 3.0 |  | a// | - - - [0] 20 90 90 | weekend, prev nand, next 6.0d | tactical_bench |
| 2 | Cole Palmer | Chelsea | 86 | 5.5 |  | a// | - - 90 [0] 0 34 20 | weekend, prev 5.0d, next 7.0d | injury_emerging |
| 3 | Aaron Wan-Bissaka | West Ham | 86 | 2.8 |  | a// | - 90 90 [0] 0 0 0 | weekend, prev 8.0d, next 13.0d | injury_emerging |
| 5 | Mads Hermansen | West Ham | 85 | 3.5 |  | a// | 90 90 90 [0] 0 0 0 | weekend, prev 6.0d, next 9.0d | injury_emerging |
| 17 | Jan Paul van Hecke | Brighton | 86 | 4.5 |  | a// | 90 90 90 [0] 90 90 90 | weekend, prev 7.0d, next 7.0d | tactical_bench |
| 22 | Matheus Nunes | Man City | 77 | 3.6 |  | a// | 90 90 72 [0] 90 90 90 | weekend, prev 9.0d, next 7.0d | tactical_bench |
| 24 | Bukayo Saka | Arsenal | 68 | 5.0 |  | a/100/ | 77 33 90 [0] 0 92 90 | weekend, prev 5.0d, next 7.0d | injury_emerging |
| 28 | Erling Haaland | Man City | 77 | 6.1 | C | a/100/ | 90 45 90 [0] 90 90 - | weekend, prev 6.0d, next 4.0d | rotation_congested |
| 29 | Robin Roefs | Sunderland | 86 | 3.3 |  | a// | 90 90 90 [0] 0 0 90 | midweek, prev 3.0d, next 10.0d | injury_emerging |
| 30 | Ibrahima Konaté | Liverpool | 77 | 3.9 |  | a/100/ | 90 90 78 [0] 76 90 90 | weekend, prev 11.0d, next 5.0d | tactical_bench |
| 33 | Richarlison de Andrade | Spurs | 63 | 3.5 |  | a/100/ | 90 66 60 [0] 50 90 90 | weekend, prev 6.0d, next 6.0d | tactical_bench |
| 38 | Erling Haaland | Man City | 84 | 8.0 | C | a/100/ | 90 90 90 [0] - - - | weekend, prev 4.0d, next nand | unclear |
| 38 | Leandro Trossard | Arsenal | 82 | 5.0 |  | a/100/ | 90 90 90 [0] - - - | weekend, prev 5.0d, next nand | unclear |
| 38 | Marc Guéhi | Man City | 84 | 5.3 |  | a/100/ | 90 180 90 [0] - - - | weekend, prev 4.0d, next nand | unclear |
| 38 | Nico O'Reilly | Man City | 78 | 6.0 |  | a/100/ | 90 90 90 [0] - - - | weekend, prev 4.0d, next nand | unclear |
