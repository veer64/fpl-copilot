# Player-prop odds — tuning on 2024-25 (2026-08-24)

Governed by `Logs/props_prereg.md` §1–§5 and ADDENDUM 1. Script: `eval/measure_props_endpoint.py --tune`.
Inputs: `data/odds_props/props_consensus_2024-25.parquet` (ADDENDUM 1 build, `method = addendum1_shared_set`),
`data/walkforward_h6_2024_25.parquet` own-cutoff rows (λ_model = the incumbent's `e_goals`), vaastav
`goals_scored` for 2024-25 only. **No 2025-26 file was opened by this run** (the script's `--tune` branch loads
the tuning season only; the `--holdout` branch refuses without the pre-registered line).

## Method (as pre-registered)

- Population: 2024-25 GW8–38, single-fixture OUTFIELD player-gameweeks (amendment 2), starter band
  own-cutoff e_minutes ≥ 60, restricted to rows the market prices; partial doubles excluded (amendment 3 —
  24 flagged in the season, all doubles, so none inside the singles population). The incumbent is scored on
  the same rows.
- Candidate: λ = w·λ_mkt(m) + (1 − w)·λ_model, λ_mkt(m) = −ln(1 − p_consensus / m).
- Primary: pooled Spearman(λ, realised goals) on likely starters (own-cutoff p_start ≥ .75) and squad-relevant
  (top 30 by own-cutoff e_points within the gameweek, ranked on the incumbent's full view before restriction).
- Selection: max MEAN of the two; ties → lower w, then lower m. Grid w ∈ {0, .25, .5, .75, 1} × m ∈ {1.00, 1.10, 1.20, 1.30}.
- Robustness guard added before the run at the user's request (not a change to the rule): the surface with
  Salah excluded; top-5 per-player contributions to ρ and to Δρ (Pearson-on-ranks terms, summed per player —
  they add to the statistic exactly); leave-one-out argmax for every listed player.
- Written-off band: p_start < .25 with NO e_minutes floor (the pre-registered starter band contains no
  written-off rows, so the §3(2) check would be empty otherwise). Stated here because it is a choice.

## Structural notes on the surface

- Rows w = 0 (no market) are identical across m by construction, and rows w = 1 are identical across m because
  Spearman is invariant to the monotone map p → p/m. m only acts at intermediate w.
- Uncertain-band Spearman is invariant to dropping Salah (he is never in that band); the numbers repeat.

## Output of record (verbatim)

```
TUNING on 2024-25 GW8-38 only (no 2025-26 file read). Outfield singles in window: 19,710; priced 11,606. Partial doubles flagged in the season and excluded: 24 (all doubles; the population is singles).
coverage of each partition by the market (share of partition rows the market prices): likely starters 90.3% of 4347; squad-relevant 97.5% of 638; uncertain 88.3% of 409; full starter band 90.1% of 4756; written off (no e_minutes floor) 40.0% of 11788

FULL GRID -- pooled Spearman(lambda, goals) on the common population, 2024-25 GW8-38; n likely starters 3924, n squad-relevant 622
      w     m |   likely    squad     MEAN | uncertain  starter writtenoff
   0.00  1.00 |   0.2750   0.2866   0.2808 |    0.3172   0.2784     0.1401
   0.00  1.10 |   0.2750   0.2866   0.2808 |    0.3172   0.2784     0.1401
   0.00  1.20 |   0.2750   0.2866   0.2808 |    0.3172   0.2784     0.1401
   0.00  1.30 |   0.2750   0.2866   0.2808 |    0.3172   0.2784     0.1401
   0.25  1.00 |   0.2802   0.2982   0.2892 |    0.3301   0.2840     0.1221
   0.25  1.10 |   0.2799   0.2976   0.2888 |    0.3287   0.2837     0.1231
   0.25  1.20 |   0.2796   0.2966   0.2881 |    0.3288   0.2834     0.1240
   0.25  1.30 |   0.2794   0.2955   0.2874 |    0.3279   0.2831     0.1249
   0.50  1.00 |   0.2829   0.3062   0.2946 |    0.3375   0.2867     0.1144
   0.50  1.10 |   0.2827   0.3056   0.2941 |    0.3368   0.2866     0.1151
   0.50  1.20 |   0.2826   0.3046   0.2936 |    0.3354   0.2864     0.1157
   0.50  1.30 |   0.2823   0.3037   0.2930 |    0.3343   0.2861     0.1163
   0.75  1.00 |   0.2837   0.3108   0.2973 |    0.3385   0.2875     0.1103
   0.75  1.10 |   0.2837   0.3101   0.2969 |    0.3391   0.2875     0.1107
   0.75  1.20 |   0.2837   0.3100   0.2968 |    0.3388   0.2875     0.1109
   0.75  1.30 |   0.2836   0.3092   0.2964 |    0.3390   0.2875     0.1112
   1.00  1.00 |   0.2828   0.3100   0.2964 |    0.3396   0.2866     0.1077
   1.00  1.10 |   0.2828   0.3100   0.2964 |    0.3396   0.2866     0.1077
   1.00  1.20 |   0.2828   0.3100   0.2964 |    0.3396   0.2866     0.1077
   1.00  1.30 |   0.2828   0.3100   0.2964 |    0.3396   0.2866     0.1077

SELECTED by the pre-registered rule (max MEAN over the two decision partitions; ties -> lower w, lower m): w = 0.75, m = 1.00  mean 0.2973
incumbent (w = 0): likely 0.2750, squad 0.2866, mean 0.2808; delta of the selected pair: likely +0.0087, squad +0.0243

ROBUSTNESS -- the same grid with Salah (element 328) EXCLUDED; his rows: 27 (likely 27, squad 27)
      w     m |   likely    squad     MEAN | uncertain  starter writtenoff
   0.00  1.00 |   0.2635   0.2529   0.2582 |    0.3172   0.2679     0.1401
   0.00  1.10 |   0.2635   0.2529   0.2582 |    0.3172   0.2679     0.1401
   0.00  1.20 |   0.2635   0.2529   0.2582 |    0.3172   0.2679     0.1401
   0.00  1.30 |   0.2635   0.2529   0.2582 |    0.3172   0.2679     0.1401
   0.25  1.00 |   0.2689   0.2660   0.2675 |    0.3301   0.2738     0.1221
   0.25  1.10 |   0.2686   0.2654   0.2670 |    0.3287   0.2734     0.1231
   0.25  1.20 |   0.2683   0.2641   0.2662 |    0.3288   0.2731     0.1240
   0.25  1.30 |   0.2681   0.2629   0.2655 |    0.3279   0.2728     0.1249
   0.50  1.00 |   0.2717   0.2749   0.2733 |    0.3375   0.2765     0.1144
   0.50  1.10 |   0.2715   0.2743   0.2729 |    0.3368   0.2764     0.1151
   0.50  1.20 |   0.2713   0.2732   0.2723 |    0.3354   0.2762     0.1157
   0.50  1.30 |   0.2711   0.2721   0.2716 |    0.3343   0.2759     0.1163
   0.75  1.00 |   0.2725   0.2797   0.2761 |    0.3385   0.2774     0.1103
   0.75  1.10 |   0.2725   0.2789   0.2757 |    0.3391   0.2774     0.1107
   0.75  1.20 |   0.2725   0.2788   0.2756 |    0.3388   0.2773     0.1109
   0.75  1.30 |   0.2724   0.2780   0.2752 |    0.3390   0.2773     0.1112
   1.00  1.00 |   0.2716   0.2789   0.2753 |    0.3396   0.2764     0.1077
   1.00  1.10 |   0.2716   0.2789   0.2753 |    0.3396   0.2764     0.1077
   1.00  1.20 |   0.2716   0.2789   0.2753 |    0.3396   0.2764     0.1077
   1.00  1.30 |   0.2716   0.2789   0.2753 |    0.3396   0.2764     0.1077
  argmax without Salah: w = 0.75, m = 1.00 mean 0.2761 -> SAME pair as the full surface

  likely starters: rho(candidate) 0.2837, delta vs incumbent +0.0087 -- per-player shares (sum to the statistic)
    top 5 by contribution to rho(candidate):
      Mohamed Salah                    rows  27 goals 20  rho share +0.0184 (+6.5% of rho)  delta share +0.0000
      Alexander Isak                   rows  23 goals 17  rho share +0.0144 (+5.1% of rho)  delta share +0.0001
      Yoane Wissa                      rows  29 goals 14  rho share +0.0118 (+4.2% of rho)  delta share -0.0008
      Erling Haaland                   rows  23 goals 11  rho share +0.0105 (+3.7% of rho)  delta share -0.0000
      Chris Wood                       rows  24 goals 13  rho share +0.0088 (+3.1% of rho)  delta share +0.0001
    top 5 by |contribution to delta rho| (candidate - incumbent):
      Sander Berge                     rows  23 goals  0  delta share -0.0018  rho share +0.0011
      Bryan Mbeumo                     rows  31 goals 14  delta share +0.0016  rho share +0.0084
      Moisés Caicedo Corozo            rows  31 goals  1  delta share -0.0016  rho share +0.0010
      Max Kilman                       rows  28 goals  0  delta share +0.0015  rho share +0.0027
      Bilal El Khannouss               rows  17 goals  0  delta share -0.0013  rho share -0.0002

  squad-relevant: rho(candidate) 0.3108, delta vs incumbent +0.0243 -- per-player shares (sum to the statistic)
    top 5 by contribution to rho(candidate):
      Mohamed Salah                    rows  27 goals 20  rho share +0.0551 (+17.7% of rho)  delta share +0.0012
      Alexander Isak                   rows  15 goals 14  rho share +0.0379 (+12.2% of rho)  delta share +0.0052
      Erling Haaland                   rows  22 goals 10  rho share +0.0256 (+8.2% of rho)  delta share +0.0003
      William Saliba                   rows  11 goals  0  rho share +0.0146 (+4.7% of rho)  delta share +0.0035
      Joško Gvardiol                   rows  18 goals  1  rho share +0.0125 (+4.0% of rho)  delta share +0.0017
    top 5 by |contribution to delta rho| (candidate - incumbent):
      Alexander Isak                   rows  15 goals 14  delta share +0.0052  rho share +0.0379
      Gabriel dos Santos Magalhães     rows  17 goals  1  delta share +0.0042  rho share +0.0113
      Jarrod Bowen                     rows   6 goals  3  delta share +0.0038  rho share +0.0023
      Amad Diallo                      rows   1 goals  3  delta share +0.0036  rho share +0.0021
      William Saliba                   rows  11 goals  0  delta share +0.0035  rho share +0.0146

  leave-one-out argmax for every player listed above:
    drop Mohamed Salah                    (likely starters) -> w = 0.75, m = 1.00  same
    drop Alexander Isak                   (likely starters) -> w = 0.75, m = 1.00  same
    drop Yoane Wissa                      (likely starters) -> w = 1, m = 1.00  CHANGES the argmax
    drop Erling Haaland                   (likely starters) -> w = 0.75, m = 1.00  same
    drop Chris Wood                       (likely starters) -> w = 0.75, m = 1.00  same
    drop Sander Berge                     (likely starters) -> w = 0.75, m = 1.00  same
    drop Bryan Mbeumo                     (likely starters) -> w = 0.75, m = 1.00  same
    drop Moisés Caicedo Corozo            (likely starters) -> w = 0.75, m = 1.00  same
    drop Max Kilman                       (likely starters) -> w = 0.75, m = 1.00  same
    drop Bilal El Khannouss               (likely starters) -> w = 0.75, m = 1.00  same
    drop Mohamed Salah                    (squad-relevant ) -> w = 0.75, m = 1.00  same
    drop Alexander Isak                   (squad-relevant ) -> w = 0.75, m = 1.00  same
    drop Erling Haaland                   (squad-relevant ) -> w = 0.75, m = 1.00  same
    drop William Saliba                   (squad-relevant ) -> w = 0.75, m = 1.00  same
    drop Joško Gvardiol                   (squad-relevant ) -> w = 0.75, m = 1.00  same
    drop Gabriel dos Santos Magalhães     (squad-relevant ) -> w = 0.75, m = 1.00  same
    drop Jarrod Bowen                     (squad-relevant ) -> w = 0.75, m = 1.00  same
    drop Amad Diallo                      (squad-relevant ) -> w = 0.75, m = 1.00  same

--- 2024-25 tuning season (NOT evidence): w = 0.75, m = 1.00 vs incumbent (w = 0) on the common population; partial doubles excluded: 24 ---
  partition                               n   Spearman inc  Spearman cand    delta
  likely starters                      3924         0.2750         0.2837  +0.0087
  squad-relevant                        622         0.2866         0.3108  +0.0243
  uncertain                             361         0.3172         0.3385  +0.0213
  full starter band                    4285         0.2784         0.2875  +0.0092
  written off (no e_minutes floor)     4716         0.1401         0.1103  -0.0298
  secondary (incumbent -> candidate):
    likely starters                    Brier 0.0879->0.0884  logloss 0.3032->0.3068  mean pred/realised 0.122/0.108->0.153/0.108  MAE 0.1986->0.2252  RMSE 0.3430->0.3417  MAE by outcome 0/1/2+ 0.125/0.735/1.671 -> 0.160/0.690/1.622
    squad-relevant                     Brier 0.1677->0.1655  logloss 0.5080->0.5038  mean pred/realised 0.306/0.227->0.313/0.227  MAE 0.4215->0.4224  RMSE 0.5324->0.5173  MAE by outcome 0/1/2+ 0.355/0.505/1.512 -> 0.361/0.491/1.480
    uncertain                          Brier 0.0793->0.0806  logloss 0.2707->0.2837  mean pred/realised 0.113/0.100->0.157/0.100  MAE 0.1835->0.2212  RMSE 0.3178->0.3195  MAE by outcome 0/1/2+ 0.113/0.739/1.702 -> 0.162/0.675/1.586
    full starter band                  Brier 0.0872->0.0877  logloss 0.3004->0.3049  mean pred/realised 0.121/0.107->0.154/0.107  MAE 0.1973->0.2248  RMSE 0.3410->0.3398  MAE by outcome 0/1/2+ 0.124/0.735/1.674 -> 0.160/0.689/1.619
    written off (no e_minutes floor)   Brier 0.0121->0.0260  logloss 0.0561->0.1418  mean pred/realised 0.013/0.013->0.112/0.013  MAE 0.0254->0.1306  RMSE 0.1244->0.1829  MAE by outcome 0/1/2+ 0.013/0.945/2.104 -> 0.121/0.774/1.918
  reliability deciles, full starter band (incumbent | candidate): n, mean predicted P(>=1), realised
    d0: n  429  0.016/0.023 | 0.042/0.030
    d1: n  428  0.026/0.030 | 0.055/0.023
    d2: n  429  0.036/0.040 | 0.066/0.037
    d3: n  428  0.050/0.028 | 0.079/0.037
    d4: n  429  0.066/0.044 | 0.096/0.040
    d5: n  428  0.088/0.084 | 0.122/0.065
    d6: n  428  0.122/0.119 | 0.159/0.110
    d7: n  429  0.167/0.170 | 0.216/0.166
    d8: n  428  0.235/0.213 | 0.286/0.229
    d9: n  429  0.406/0.317 | 0.416/0.331

Salah guard passed (argmax unchanged without him). Write the selected pair into a dated '## PRE-REGISTERED VALUE' section of Logs/props_prereg.md as the exact line 'w = 0.75, m = 1.00' BEFORE running --holdout. 2025-26 has not been read.
```
