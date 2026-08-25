# Player-prop name crosswalk — precision report (2026-08-24)

Built by `eval/build_props_crosswalk.py` before any de-vig or feature, per `Logs/props_prereg.md` §7.4. Method: candidates = the fixture's two clubs' players at that gameweek (vaastav `team` per gw); tiers exact (normalised full name) → token-subset (one name's tokens contained in the other's, unique in the pool) → discriminating token (a ≥4-char token identifying exactly one player in the two squads, `fuzz.ratio ≥ 85`) → fuzzy (`token_set_ratio` ≥ 88 with margin ≥ 4 over the runner-up, the build_crosswalk floor). Every row carries `match_type`; unmatched rows are null, counted and named. Within every board one name → one element and one element → one name (`assert_crosswalk_unique` semantics); the same normalised name maps to the same element across the season.

## 2024-25

- **Match rate:** 11,958 of 12,120 priced name-rows (98.66%) across 310 fixtures; 26 distinct unmatched names (162 rows), left null.
- **Provenance:** exact 9,868, token_subset 1,628, club+token 300, manual 162. Distinct fuzzy pairs 0, surname-token pairs 13, token-subset pairs 65 (all listed below); manual entries 9 names / 162 rows (table below), manual conflicts 0, manual entries refused because the element was not at a fixture club that gameweek 0.
- **assert_crosswalk_unique:** 1,638 per-book boards asserted (no element claimed twice, no name mapped twice), 0 raised.

**Manual entries applied (evidence recorded in `match_evidence`; each auditable without this session):**

| book name | → FPL name (element) | rows | evidence |
|---|---|---|---|
| Beto | Norberto Bercique Gomes Betuncal (218) | 31 | Norberto Bercique Gomes Betuncal | Everton GW1-38, FWD, 1521 min / 8 goals | the only Beto at Everton; KNOWN_ISSUES #3 precedent (no token of the legal name matches the playing name) |
| Casemiro | Carlos Henrique Casimiro (368) | 31 | Carlos Henrique Casimiro | Man Utd GW1-38, MID, 1489 min / 1 goal | single-token book name; the only 'Casimiro' at Man Utd; spelling Casemiro/Casimiro is the known FPL variant |
| Diogo Jota | Diogo Teixeira da Silva (317) | 31 | Diogo Teixeira da Silva | Liverpool GW1-38, MID, 1182 min / 6 goals | the only Diogo at Liverpool (Dalot is Man Utd, club-excluded); legal name Diogo Jose Teixeira da Silva |
| Emerson | Emerson Palmieri dos Santos (520) | 2 | Emerson Palmieri dos Santos | West Ham GW1-38, DEF, 2108 min / 2 goals | single-token book name on all 30 West Ham boards at 0.05-0.13 implied (a starting full-back); in the two Spurs-v-West Ham boards (GW8, GW35) Emerson Leite de Souza Junior (Emerson Royal, el 487, Spurs DEF) is also in the pool -- he transferred to AC Milan in Aug 2024 and has 0 minutes all season, so the identification is certain and stated |
| Fatawu Issahaku | Abdul Fatawu (570) | 4 | Abdul Fatawu | Leicester GW1-38, MID, 576 min / 0 goals | Abdul Fatawu Issahaku; the only Fatawu at Leicester; the given-name tier rejected 'fatawu'/'abdul' correctly, the surname is the FPL given name |
| João Pedro | João Pedro Junqueira de Jesus (129) | 1 | Joao Pedro Junqueira de Jesus | Brighton GW1-38, FWD, 1946 min / 10 goals | the automated tier maps this key to 129 in 26 Brighton boards; the single null is GW24 Forest v Brighton where Forest's Joao Pedro Ferreira Silva (596) shares the pool -- that board lists 'Jota Silva' separately (matched to 596), so 'Joao Pedro' there is the Brighton player. Resolved on that evidence only |
| Jorginho | Jorge Luiz Frello Filho (7) | 30 | Jorge Luiz Frello Filho | Arsenal GW1-38, MID, 701 min / 0 goals | single-token playing name; legal name carries no matching token; the only candidate at Arsenal |
| Jota Silva | João Pedro Ferreira Silva (596) | 1 | Joao Pedro Ferreira Silva | Nott'm Forest GW1-38, MID, 835 min / 3 goals | the surname tier maps this key to 596 in every other Forest board; the single null is GW20 Wolves v Forest where Wolves carries another 'Silva' so the surname token is not unique; manual entry restores cross-fixture consistency |
| Lucas Paquetá | Lucas Tolentino Coelho de Lima (527) | 31 | Lucas Tolentino Coelho de Lima | West Ham GW1-38, MID, 2374 min / 4 goals | book name on all 31 West Ham boards; the only Lucas at West Ham (other Lucas elements: Digne Villa, Bergstrom Chelsea, Bergvall Spurs -- club-excluded); FPL carries the legal name, the books the playing name 'Paqueta' |
- **Uniqueness:** per-book board violations 0; cross-book multi-spellings of one element 0 (e.g. "Josh King" / "Joshua King" — the consensus must merge by element, not by string); cross-fixture name→element inconsistencies 0.
- **Placeholder prices:** 175 matched rows (24 players) with < 90 season minutes priced at mean implied ≥ 0.25 — youth/fringe names carried on boards at short prices; a data-quality item for the de-vig step, not a matching error.
- **Team audit:** 0 matched rows whose element's club is not in the fixture.
- **Homonyms:** 0 exact-matched names that also exist at another club this season (listed).
- **Plausibility flags:** 0 price/position (GK ≥ .15 or DEF ≥ .35 mean implied), 305 price/minutes (played 0 with mean implied ≥ .30).
- **Outfield starters not covered:** 118 players / 681 player-fixtures / 56,826 minutes of 503,717 outfield starter minutes in priced fixtures → outfield starter coverage **88.57%**. Split: **unpriced** (no candidate name on the board) 672 player-fixtures; **unmatched with a candidate name** 0 player-fixtures across 0 players — the manual-pass list below. Goalkeepers are not priced on these boards (40 GKs, 57,040 minutes) and are excluded.

**Top uncovered OUTFIELD starters by minutes (played ≥60 in a priced fixture, no book name mapped to them; mostly unpriced):**

| player | team | pos | fixtures | minutes |
|---|---|---|---|---|
| Nikola Milenković | Nott'm Forest | DEF | 31 | 2790 |
| Noussair Mazraoui | Man Utd | DEF | 25 | 2134 |
| Sepp van den Berg | Brentford | DEF | 24 | 2132 |
| Sam Morsy | Ipswich | MID | 24 | 2097 |
| Wout Faes | Leicester | DEF | 23 | 2070 |
| Iliman Ndiaye | Everton | FWD | 23 | 1915 |
| André Trindade da Costa Neto | Wolves | MID | 22 | 1849 |
| Victor Kristiansen | Leicester | DEF | 19 | 1682 |
| Wilfred Ndidi | Leicester | MID | 20 | 1661 |
| Emmanuel Agbadou | Wolves | DEF | 16 | 1410 |
| Sávio 'Savinho' Moreira de Oliveira | Man City | MID | 17 | 1400 |
| Mikel Merino | Arsenal | MID | 16 | 1353 |
| Omar Marmoush | Man City | FWD | 16 | 1327 |
| Yankuba Minteh | Brighton | MID | 15 | 1201 |
| Ryan Manning | Southampton | DEF | 14 | 1144 |
| Tyler Dibling | Southampton | MID | 14 | 1120 |
| Tosin Adarabioyo | Chelsea | DEF | 12 | 1072 |
| Trevoh Chalobah | Crystal Palace | DEF | 11 | 973 |
| Marshall Munetsi | Wolves | MID | 11 | 964 |
| Mathys Tel | Spurs | MID | 11 | 903 |

**Unmatched WITH a candidate name — the proposed MANUAL pass (not applied; each needs club + position + minutes evidence):**

| FPL name | team | pos | book name(s) on the board | fixtures | minutes |
|---|---|---|---|---|---|

**Unmatched book names, by mean implied probability (top 25 of 26):**

| book name | fixture (first) | books | mean implied | best candidate score |
|---|---|---|---|---|
| Jayden Danns | GW18 Liverpool v Leicester | 2 | 0.565 | unmatched(best=64,runner=48) |
| Damola Ajayi | GW11 Spurs v Ipswich | 4 | 0.373 | unmatched(best=56,runner=43) |
| Kobei Moore | GW14 Aston Villa v Brentford | 2 | 0.364 | unmatched(best=56,runner=48) |
| Tyrique George | GW14 Southampton v Chelsea | 2 | 0.340 | unmatched(best=52,runner=45) |
| Treymaurice Nyoni | GW10 Liverpool v Brighton | 2 | 0.323 | unmatched(best=44,runner=43) |
| Daniel Gore | GW11 Man Utd v Leicester | 1 | 0.267 | unmatched(best=72,runner=67) |
| Thiago Silva | GW16 Chelsea v Brentford | 1 | 0.263 | unmatched(best=67,runner=58) |
| Martin Sherif | GW10 Southampton v Everton | 1 | 0.250 | unmatched(best=52,runner=52) |
| Lewis Orford | GW9 West Ham v Man Utd | 1 | 0.231 | unmatched(best=57,runner=52) |
| Kiano Dyer | GW14 Southampton v Chelsea | 2 | 0.229 | unmatched(best=52,runner=48) |
| Tyrese Hall | GW23 Spurs v Leicester | 3 | 0.212 | unmatched(best=48,runner=48) |
| Jacob Wright | GW9 Man City v Southampton | 1 | 0.211 | unmatched(best=42,runner=40) |
| Dante Cassanova | GW10 Spurs v Aston Villa | 1 | 0.182 | unmatched(best=48,runner=46) |
| Jamaldeen Jimoh | GW15 Aston Villa v Southampton | 1 | 0.167 | unmatched(best=61,runner=53) |
| Ben Broggio | GW10 Spurs v Aston Villa | 1 | 0.133 | unmatched(best=57,runner=55) |
| Kaden Braithwaite | GW36 Southampton v Man City | 1 | 0.133 | unmatched(best=50,runner=45) |
| Josh Acheampong | GW14 Southampton v Chelsea | 2 | 0.125 | unmatched(best=55,runner=47) |
| Habeeb Ogunneye | GW12 Ipswich v Man Utd | 1 | 0.125 | unmatched(best=52,runner=50) |
| Aidan Borland | GW10 Spurs v Aston Villa | 1 | 0.111 | unmatched(best=67,runner=58) |
| Alfie Dorrington | GW8 Spurs v West Ham | 1 | 0.105 | unmatched(best=64,runner=60) |
| Luke Butterfield | GW14 Everton v Wolves | 2 | 0.104 | unmatched(best=53,runner=50) |
| Bradley Moonan | GW12 Everton v Brentford | 1 | 0.083 | unmatched(best=57,runner=54) |
| Zach Abbott | GW13 Nott'm Forest v Ipswich | 1 | 0.083 | unmatched(best=50,runner=38) |
| Max Kinsey | GW11 Brentford v Bournemouth | 1 | 0.083 | unmatched(best=60,runner=50) |
| Harry Amass | GW8 Man Utd v Brentford | 3 | 0.073 | unmatched(best=67,runner=46) |

**Fuzzy matches (ALL — where silent errors live): 0**


**Discriminating-token matches (ALL): 13**

| book name | → FPL name | team | pos | score | mean implied | gw |
|---|---|---|---|---|---|---|
| Ben White | Benjamin White | Arsenal | DEF | 90 | 0.084 | 8 |
| Joshua King | Josh King | Fulham | MID | 90 | 0.125 | 8 |
| Andy Robertson | Andrew Robertson | Liverpool | DEF | 90 | 0.082 | 8 |
| Kostas Tsimikas | Konstantinos Tsimikas | Liverpool | DEF | 90 | 0.075 | 8 |
| Jota Silva | João Pedro Ferreira Silva | Nott'm Forest | MID | 90 | 0.272 | 10 |
| Andrew Irving | Andy Irving | West Ham | MID | 90 | 0.154 | 10 |
| Jesper Lindstrom | Jesper Lindstrøm | Everton | MID | 90 | 0.203 | 10 |
| Lamar Bogarde | Lamare Bogarde | Aston Villa | DEF | 90 | 0.111 | 10 |
| Harrison Clarke | Harry Clarke | Ipswich | DEF | 90 | 0.047 | 11 |
| Oliver Scarles | Ollie Scarles | West Ham | DEF | 90 | 0.079 | 12 |
| Maximilian Kilman | Max Kilman | West Ham | DEF | 90 | 0.071 | 15 |
| Jjames McConnell | James McConnell | Liverpool | MID | 90 | 0.167 | 16 |
| Wesley Okoduwa | Wes Okoduwa | Wolves | DEF | 90 | 0.048 | 21 |

**Token-subset matches (ALL): 65**

| book name | → FPL name | team | pos | score | mean implied | gw |
|---|---|---|---|---|---|---|
| Takehiro Tomiyasu | Tomiyasu Takehiro | Arsenal | DEF | 95 | 0.072 | 8 |
| Gabriel Martinelli | Gabriel Martinelli Silva | Arsenal | MID | 95 | 0.296 | 8 |
| Gabriel Jesus | Gabriel Fernando de Jesus | Arsenal | FWD | 95 | 0.328 | 8 |
| Gabriel Magalhães | Gabriel dos Santos Magalhães | Arsenal | DEF | 95 | 0.140 | 8 |
| Andreas Pereira | Andreas Hoelgebaum Pereira | Fulham | MID | 95 | 0.192 | 8 |
| Ezri Konsa | Ezri Konsa Ngoyo | Aston Villa | DEF | 95 | 0.051 | 8 |
| Diego Carlos | Diego Carlos Santos Silva | Aston Villa | DEF | 95 | 0.053 | 8 |
| Rodrigo Muniz | Rodrigo Muniz Carvalho | Fulham | FWD | 95 | 0.356 | 8 |
| Emiliano Buendía | Emiliano Buendía Stati | Aston Villa | MID | 95 | 0.188 | 8 |
| Omari Hutchinson | Omari Giraud-Hutchinson | Ipswich | MID | 95 | 0.248 | 8 |
| Youssef Chermiti | Youssef Ramalho Chermiti | Everton | FWD | 95 | 0.227 | 8 |
| Wataru Endo | Endo Wataru | Liverpool | MID | 95 | 0.124 | 8 |
| Marc Cucurella | Marc Cucurella Saseta | Chelsea | DEF | 95 | 0.059 | 8 |
| Moisés Caicedo | Moisés Caicedo Corozo | Chelsea | MID | 95 | 0.073 | 8 |
| Deivid Washington | Deivid Washington de Souza Eugênio | Chelsea | FWD | 95 | 0.200 | 8 |
| Darwin Núñez | Darwin Núñez Ribeiro | Liverpool | FWD | 95 | 0.399 | 8 |
| Bruno Fernandes | Bruno Borges Fernandes | Man Utd | MID | 95 | 0.347 | 8 |
| Diogo Dalot | Diogo Dalot Teixeira | Man Utd | DEF | 95 | 0.081 | 8 |
| Antony | Antony Matheus dos Santos | Man Utd | MID | 95 | 0.275 | 8 |
| Mads Roerslev | Mads Roerslev Rasmussen | Brentford | DEF | 95 | 0.055 | 8 |
| Yunus Konak | Yunus Emre Konak | Brentford | MID | 95 | 0.082 | 8 |
| Kaoru Mitoma | Mitoma Kaoru | Brighton | MID | 95 | 0.234 | 8 |
| Bruno Guimarães | Bruno Guimarães Rodriguez Moura | Newcastle | MID | 95 | 0.144 | 8 |
| Miguel Almirón | Miguel Almirón Rejala | Newcastle | MID | 95 | 0.263 | 8 |
| Joelinton | Joelinton Cássio Apolinário de Lira | Newcastle | MID | 95 | 0.199 | 8 |
| Igor Julio | Igor Julio dos Santos de Paulo | Brighton | DEF | 95 | 0.050 | 8 |
| Jefferson Lerma | Jefferson Lerma Solís | Crystal Palace | MID | 95 | 0.099 | 8 |
| Willy-Arnaud Boly | Willy Boly | Nott'm Forest | DEF | 95 | 0.068 | 8 |
| Murillo | Murillo Santiago Costa dos Santos | Nott'm Forest | DEF | 95 | 0.046 | 8 |
| Felipe | Felipe Rodrigues da Silva | Nott'm Forest | DEF | 95 | 0.077 | 8 |
| Pape Sarr | Pape Matar Sarr | Spurs | MID | 95 | 0.205 | 8 |
| Edson Álvarez | Edson Álvarez Velázquez | West Ham | MID | 95 | 0.079 | 8 |
| Richarlison | Richarlison de Andrade | Spurs | FWD | 95 | 0.465 | 8 |
| Bernardo Silva | Bernardo Veiga de Carvalho e Silva | Man City | MID | 95 | 0.240 | 8 |
| Nélson Semedo | Nélson Cabral Semedo | Wolves | DEF | 95 | 0.049 | 8 |
| Rúben Dias | Rúben Gato Alves Dias | Man City | DEF | 95 | 0.094 | 8 |
| Matheus Cunha | Matheus Santos Carneiro Da Cunha | Wolves | FWD | 95 | 0.232 | 8 |
| Matheus Nunes | Matheus Luiz Nunes | Man City | MID | 95 | 0.141 | 8 |
| Toti Gomes | Toti António Gomes | Wolves | DEF | 95 | 0.048 | 8 |
| João Gomes | João Victor Gomes da Silva | Wolves | MID | 95 | 0.068 | 8 |
| Emerson | Emerson Palmieri dos Santos | West Ham | DEF | 95 | 0.069 | 9 |
| Evanilson | Francisco Evanilson de Lima Barbosa | Bournemouth | FWD | 95 | 0.244 | 10 |
| Julián Araujo | Julián Araujo Zúñiga | Bournemouth | DEF | 95 | 0.048 | 10 |
| Fábio Carvalho | Fábio Freitas Gouveia Carvalho | Brentford | MID | 95 | 0.246 | 10 |
| Jorge Cuenca | Jorge Cuenca Barreno | Fulham | DEF | 95 | 0.084 | 10 |
| Carlos Vinícius | Carlos Vinícius Alves Morais | Fulham | FWD | 95 | 0.333 | 10 |
| Gustavo Nunes | Gustavo Nunes Fernandes Gomes | Brentford | MID | 95 | 0.167 | 10 |
| João Pedro | João Pedro Junqueira de Jesus | Brighton | FWD | 95 | 0.246 | 10 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.328 | 10 |
| João Félix | João Félix Sequeira | Chelsea | MID | 95 | 0.299 | 10 |
| Pedro Neto | Pedro Lomba Neto | Chelsea | MID | 95 | 0.227 | 10 |
| Luis Guilherme | Luis Guilherme Lira dos Santos | West Ham | MID | 95 | 0.123 | 10 |
| Álex Moreno | Álex Moreno Lopera | Nott'm Forest | DEF | 95 | 0.082 | 10 |
| Mateus Fernandes | Mateus Gonçalo Espanha Fernandes | Southampton | MID | 95 | 0.159 | 10 |
| Dominic Solanke | Dominic Solanke-Mitchell | Spurs | FWD | 95 | 0.396 | 10 |
| Goncalo Guedes | Gonçalo Manuel Ganchinho Guedes | Wolves | MID | 95 | 0.258 | 10 |
| Carlos Forbs | Carlos Roberto Forbs Borges | Wolves | MID | 95 | 0.186 | 10 |
| Chadi Riad | Chadi Riad Dnanou | Crystal Palace | DEF | 95 | 0.067 | 11 |
| Matheus França | Matheus França de Oliveira | Crystal Palace | MID | 95 | 0.182 | 11 |
| Neto | André Trindade da Costa Neto | Wolves | MID | 95 | 0.111 | 13 |
| Danilo | Danilo dos Santos de Oliveira | Nott'm Forest | MID | 95 | 0.135 | 20 |
| Nathan Wood | Nathan Wood-Gordon | Southampton | DEF | 95 | 0.051 | 21 |
| Pedro Lima | Pedro Cardoso de Lima | Wolves | DEF | 95 | 0.042 | 21 |
| Willian | Willian Borges da Silva | Fulham | MID | 95 | 0.205 | 25 |
| Rodri | Rodrigo 'Rodri' Hernandez | Man City | MID | 95 | 0.238 | 36 |

**Exact matches with a same-name player at another club (homonyms): 0**


**Price/position flags: 0**


**Price/minutes flags: 304**

| book name | → FPL name | team | pos | score | mean implied | gw |
|---|---|---|---|---|---|---|
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.328 | 10 |
| Richarlison | Richarlison de Andrade | Spurs | FWD | 95 | 0.476 | 11 |
| Gabriel Martinelli | Gabriel Martinelli Silva | Arsenal | MID | 95 | 0.312 | 12 |
| Carlos Vinícius | Carlos Vinícius Alves Morais | Fulham | FWD | 95 | 0.385 | 12 |
| Dominic Solanke | Dominic Solanke-Mitchell | Spurs | FWD | 95 | 0.316 | 35 |
| Carlos Vinícius | Carlos Vinícius Alves Morais | Fulham | FWD | 95 | 0.335 | 36 |
| Gustavo Nunes | Gustavo Nunes Fernandes Gomes | Brentford | MID | 95 | 0.376 | 36 |
| Dominic Solanke | Dominic Solanke-Mitchell | Spurs | FWD | 95 | 0.326 | 36 |
| Richarlison | Richarlison de Andrade | Spurs | FWD | 95 | 0.322 | 36 |
| Rodrigo Muniz | Rodrigo Muniz Carvalho | Fulham | FWD | 95 | 0.349 | 37 |
| João Pedro | João Pedro Junqueira de Jesus | Brighton | FWD | 95 | 0.349 | 37 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.371 | 37 |
| Youssef Chermiti | Youssef Ramalho Chermiti | Everton | FWD | 95 | 0.365 | 37 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.366 | 34 |
| Rodrigo Muniz | Rodrigo Muniz Carvalho | Fulham | FWD | 95 | 0.441 | 34 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.346 | 35 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.395 | 12 |
| Pedro Neto | Pedro Lomba Neto | Chelsea | MID | 95 | 0.304 | 12 |
| Gustavo Nunes | Gustavo Nunes Fernandes Gomes | Brentford | MID | 95 | 0.371 | 13 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.360 | 13 |
| Dominic Solanke | Dominic Solanke-Mitchell | Spurs | FWD | 95 | 0.442 | 13 |
| Kaoru Mitoma | Mitoma Kaoru | Brighton | MID | 95 | 0.342 | 32 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.435 | 32 |
| Darwin Núñez | Darwin Núñez Ribeiro | Liverpool | FWD | 95 | 0.402 | 32 |
| Rodrigo Muniz | Rodrigo Muniz Carvalho | Fulham | FWD | 95 | 0.347 | 33 |
| Darwin Núñez | Darwin Núñez Ribeiro | Liverpool | FWD | 95 | 0.421 | 33 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.415 | 30 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.345 | 31 |
| Matheus Cunha | Matheus Santos Carneiro Da Cunha | Wolves | FWD | 95 | 0.333 | 31 |
| Richarlison | Richarlison de Andrade | Spurs | FWD | 95 | 0.449 | 31 |
| Richarlison | Richarlison de Andrade | Spurs | FWD | 95 | 0.352 | 28 |
| Matheus Cunha | Matheus Santos Carneiro Da Cunha | Wolves | FWD | 95 | 0.312 | 28 |
| Carlos Vinícius | Carlos Vinícius Alves Morais | Fulham | FWD | 95 | 0.326 | 29 |
| Matheus Cunha | Matheus Santos Carneiro Da Cunha | Wolves | FWD | 95 | 0.392 | 29 |
| Matheus Cunha | Matheus Santos Carneiro Da Cunha | Wolves | FWD | 95 | 0.333 | 30 |
| Richarlison | Richarlison de Andrade | Spurs | FWD | 95 | 0.400 | 13 |
| Gabriel Martinelli | Gabriel Martinelli Silva | Arsenal | MID | 95 | 0.309 | 13 |
| Gabriel Jesus | Gabriel Fernando de Jesus | Arsenal | FWD | 95 | 0.363 | 14 |
| Richarlison | Richarlison de Andrade | Spurs | FWD | 95 | 0.347 | 14 |
| Carlos Vinícius | Carlos Vinícius Alves Morais | Fulham | FWD | 95 | 0.312 | 14 |
| Pedro Neto | Pedro Lomba Neto | Chelsea | MID | 95 | 0.336 | 14 |
| Deivid Washington | Deivid Washington de Souza Eugênio | Chelsea | FWD | 95 | 0.349 | 14 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.427 | 14 |
| Emiliano Buendía | Emiliano Buendía Stati | Aston Villa | MID | 95 | 0.307 | 15 |
| Deivid Washington | Deivid Washington de Souza Eugênio | Chelsea | FWD | 95 | 0.496 | 27 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.488 | 27 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.435 | 28 |
| Dominic Solanke | Dominic Solanke-Mitchell | Spurs | FWD | 95 | 0.407 | 25 |
| Richarlison | Richarlison de Andrade | Spurs | FWD | 95 | 0.339 | 25 |
| Deivid Washington | Deivid Washington de Souza Eugênio | Chelsea | FWD | 95 | 0.313 | 26 |
| Carlos Vinícius | Carlos Vinícius Alves Morais | Fulham | FWD | 95 | 0.313 | 26 |
| Darwin Núñez | Darwin Núñez Ribeiro | Liverpool | FWD | 95 | 0.353 | 26 |
| Richarlison | Richarlison de Andrade | Spurs | FWD | 95 | 0.323 | 15 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.369 | 15 |
| Pedro Neto | Pedro Lomba Neto | Chelsea | MID | 95 | 0.364 | 16 |
| João Félix | João Félix Sequeira | Chelsea | MID | 95 | 0.417 | 16 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.459 | 16 |
| Miguel Almirón | Miguel Almirón Rejala | Newcastle | MID | 95 | 0.349 | 16 |
| Dominic Solanke | Dominic Solanke-Mitchell | Spurs | FWD | 95 | 0.347 | 24 |
| João Félix | João Félix Sequeira | Chelsea | MID | 95 | 0.388 | 24 |
| Carlos Vinícius | Carlos Vinícius Alves Morais | Fulham | FWD | 95 | 0.310 | 25 |
| Gabriel Martinelli | Gabriel Martinelli Silva | Arsenal | MID | 95 | 0.364 | 25 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.446 | 22 |
| Dominic Solanke | Dominic Solanke-Mitchell | Spurs | FWD | 95 | 0.349 | 22 |
| Carlos Vinícius | Carlos Vinícius Alves Morais | Fulham | FWD | 95 | 0.352 | 22 |
| Carlos Vinícius | Carlos Vinícius Alves Morais | Fulham | FWD | 95 | 0.307 | 23 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.310 | 23 |
| Dominic Solanke | Dominic Solanke-Mitchell | Spurs | FWD | 95 | 0.455 | 23 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.360 | 17 |
| João Félix | João Félix Sequeira | Chelsea | MID | 95 | 0.329 | 17 |
| Richarlison | Richarlison de Andrade | Spurs | FWD | 95 | 0.308 | 17 |
| Richarlison | Richarlison de Andrade | Spurs | FWD | 95 | 0.343 | 20 |
| Darwin Núñez | Darwin Núñez Ribeiro | Liverpool | FWD | 95 | 0.381 | 21 |
| Carlos Vinícius | Carlos Vinícius Alves Morais | Fulham | FWD | 95 | 0.336 | 21 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.416 | 21 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.431 | 19 |
| Richarlison | Richarlison de Andrade | Spurs | FWD | 95 | 0.435 | 19 |
| Darwin Núñez | Darwin Núñez Ribeiro | Liverpool | FWD | 95 | 0.458 | 19 |
| João Félix | João Félix Sequeira | Chelsea | MID | 95 | 0.302 | 20 |
| Carlos Vinícius | Carlos Vinícius Alves Morais | Fulham | FWD | 95 | 0.376 | 20 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.402 | 18 |
| João Félix | João Félix Sequeira | Chelsea | MID | 95 | 0.371 | 18 |
| Richarlison | Richarlison de Andrade | Spurs | FWD | 95 | 0.323 | 18 |
| Carlos Vinícius | Carlos Vinícius Alves Morais | Fulham | FWD | 95 | 0.317 | 19 |
| Rodrigo Muniz | Rodrigo Muniz Carvalho | Fulham | FWD | 95 | 0.356 | 8 |
| Deivid Washington | Deivid Washington de Souza Eugênio | Chelsea | FWD | 95 | 0.308 | 9 |
| Carlos Vinícius | Carlos Vinícius Alves Morais | Fulham | FWD | 95 | 0.333 | 10 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.320 | 38 |
| João Pedro | João Pedro Junqueira de Jesus | Brighton | FWD | 95 | 0.400 | 38 |
| Solly March | Solly March | Brighton | MID | 100 | 0.312 | 38 |
| Danny Welbeck | Danny Welbeck | Brighton | FWD | 100 | 0.440 | 38 |
| Ismeal Kabia | Ismeal Kabia | Arsenal | MID | 100 | 0.444 | 38 |
| Christopher Nkunku | Christopher Nkunku | Chelsea | MID | 100 | 0.324 | 38 |
| Federico Chiesa | Federico Chiesa | Liverpool | MID | 100 | 0.364 | 38 |
| Danny Ings | Danny Ings | West Ham | FWD | 100 | 0.333 | 38 |
| Dominic Sadi | Dominic Sadi | Bournemouth | MID | 100 | 0.400 | 38 |
| Dango Ouattara | Dango Ouattara | Bournemouth | MID | 100 | 0.453 | 38 |
| Luis Sinisterra | Luis Sinisterra | Bournemouth | MID | 100 | 0.369 | 38 |
| Jamie Vardy | Jamie Vardy | Leicester | FWD | 100 | 0.312 | 38 |
| James McAtee | James McAtee | Man City | MID | 100 | 0.309 | 37 |
| Phil Foden | Phil Foden | Man City | MID | 100 | 0.338 | 37 |
| Stephy Mavididi | Stephy Mavididi | Leicester | MID | 100 | 0.331 | 37 |
| Martin Sherif | Martin Sherif | Everton | FWD | 100 | 0.382 | 37 |
| Diogo Jota | Diogo Teixeira da Silva | Liverpool | MID | 100 | 0.444 | 10 |
| Federico Chiesa | Federico Chiesa | Liverpool | MID | 100 | 0.391 | 10 |
| Jérémy Doku | Jérémy Doku | Man City | MID | 100 | 0.312 | 9 |
| Jack Grealish | Jack Grealish | Man City | MID | 100 | 0.301 | 9 |
| Kevin De Bruyne | Kevin De Bruyne | Man City | MID | 100 | 0.353 | 9 |
| Son Heung-Min | Son Heung-min | Spurs | MID | 100 | 0.367 | 9 |
| Callum Wilson | Callum Wilson | Newcastle | FWD | 100 | 0.346 | 9 |
| Simon Adingra | Simon Adingra | Brighton | MID | 100 | 0.308 | 9 |
| Mikey Moore | Mikey Moore | Spurs | MID | 100 | 0.348 | 8 |
| Callum Wilson | Callum Wilson | Newcastle | FWD | 100 | 0.441 | 8 |
| Ethan Wheatley | Ethan Wheatley | Man Utd | FWD | 100 | 0.323 | 8 |
| Amad Diallo | Amad Diallo | Man Utd | MID | 100 | 0.325 | 8 |
| Bukayo Saka | Bukayo Saka | Arsenal | MID | 100 | 0.351 | 8 |
| Kai Havertz | Kai Havertz | Arsenal | FWD | 100 | 0.378 | 19 |
| Ethan Wheatley | Ethan Wheatley | Man Utd | FWD | 100 | 0.304 | 18 |
| Marcus Rashford | Marcus Rashford | Man Utd | MID | 100 | 0.314 | 18 |
| Lucas Paquetá | Lucas Tolentino Coelho de Lima | West Ham | MID | 100 | 0.333 | 18 |
| Danny Ings | Danny Ings | West Ham | FWD | 100 | 0.317 | 18 |
| Cameron Archer | Cameron Archer | Southampton | FWD | 100 | 0.313 | 18 |
| Treymaurice Nyoni | Treymaurice Nyoni | Liverpool | MID | 100 | 0.325 | 18 |
| Federico Chiesa | Federico Chiesa | Liverpool | MID | 100 | 0.457 | 18 |
| Luis Díaz | Luis Díaz | Liverpool | MID | 100 | 0.516 | 18 |
| Noni Madueke | Noni Madueke | Chelsea | MID | 100 | 0.338 | 18 |
| Danny Welbeck | Danny Welbeck | Brighton | FWD | 100 | 0.390 | 18 |
| Evan Ferguson | Evan Ferguson | Brighton | FWD | 100 | 0.391 | 18 |
| Divin Mubama | Divin Mubama | Man City | FWD | 100 | 0.488 | 20 |
| Jayden Danns | Jayden Danns | Liverpool | FWD | 100 | 0.347 | 20 |
| Federico Chiesa | Federico Chiesa | Liverpool | MID | 100 | 0.373 | 20 |
| Christopher Nkunku | Christopher Nkunku | Chelsea | MID | 100 | 0.342 | 20 |
| Kai Havertz | Kai Havertz | Arsenal | FWD | 100 | 0.320 | 20 |
| Kadan Young | Kadan Young | Aston Villa | MID | 100 | 0.323 | 20 |
| Jaden Philogene | Jaden Philogene | Aston Villa | MID | 100 | 0.332 | 20 |
| Federico Chiesa | Federico Chiesa | Liverpool | MID | 100 | 0.373 | 19 |
| Mikey Moore | Mikey Moore | Spurs | MID | 100 | 0.334 | 19 |
| William Osula | William Osula | Newcastle | FWD | 100 | 0.316 | 19 |
| Tyrique George | Tyrique George | Chelsea | MID | 100 | 0.318 | 19 |
| Diogo Jota | Diogo Teixeira da Silva | Liverpool | MID | 100 | 0.422 | 22 |
| Harvey Barnes | Harvey Barnes | Newcastle | MID | 100 | 0.378 | 21 |
| Ethan Wheatley | Ethan Wheatley | Man Utd | FWD | 100 | 0.367 | 21 |
| Marcus Rashford | Marcus Rashford | Man Utd | MID | 100 | 0.431 | 21 |
| Christopher Nkunku | Christopher Nkunku | Chelsea | MID | 100 | 0.410 | 21 |
| Niclas Füllkrug | Niclas Füllkrug | West Ham | FWD | 100 | 0.312 | 21 |
| Federico Chiesa | Federico Chiesa | Liverpool | MID | 100 | 0.306 | 21 |
| Julio Enciso | Julio Enciso | Brighton | MID | 100 | 0.300 | 21 |
| Evan Ferguson | Evan Ferguson | Brighton | FWD | 100 | 0.346 | 21 |
| Jhon Durán | Jhon Durán | Aston Villa | FWD | 100 | 0.344 | 21 |
| Ismeal Kabia | Ismeal Kabia | Arsenal | MID | 100 | 0.326 | 21 |
| William Osula | William Osula | Newcastle | FWD | 100 | 0.432 | 20 |
| Luis Sinisterra | Luis Sinisterra | Bournemouth | MID | 100 | 0.300 | 18 |
| Bukayo Saka | Bukayo Saka | Arsenal | MID | 100 | 0.546 | 18 |
| Ethan Nwaneri | Ethan Nwaneri | Arsenal | MID | 100 | 0.350 | 18 |
| Danny Ings | Danny Ings | West Ham | FWD | 100 | 0.310 | 17 |
| Danny Welbeck | Danny Welbeck | Brighton | FWD | 100 | 0.318 | 17 |
| Federico Chiesa | Federico Chiesa | Liverpool | MID | 100 | 0.342 | 17 |
| Ethan Wheatley | Ethan Wheatley | Man Utd | FWD | 100 | 0.310 | 17 |
| Marcus Rashford | Marcus Rashford | Man Utd | MID | 100 | 0.335 | 17 |
| William Osula | William Osula | Newcastle | FWD | 100 | 0.368 | 17 |
| Emile Smith Rowe | Emile Smith Rowe | Fulham | MID | 100 | 0.314 | 17 |
| Ben Brereton Díaz | Ben Brereton Díaz | Southampton | MID | 100 | 0.300 | 16 |
| Mikey Moore | Mikey Moore | Spurs | MID | 100 | 0.333 | 16 |
| Taiwo Awoniyi | Taiwo Awoniyi | Nott'm Forest | FWD | 100 | 0.329 | 16 |
| Timo Werner | Timo Werner | Spurs | MID | 100 | 0.364 | 23 |
| William Osula | William Osula | Newcastle | FWD | 100 | 0.403 | 23 |
| Diogo Jota | Diogo Teixeira da Silva | Liverpool | MID | 100 | 0.545 | 23 |
| Evan Ferguson | Evan Ferguson | Brighton | FWD | 100 | 0.346 | 23 |
| Marcus Rashford | Marcus Rashford | Man Utd | MID | 100 | 0.318 | 22 |
| Oscar Bobb | Oscar Bobb | Man City | MID | 100 | 0.347 | 22 |
| Beto | Norberto Bercique Gomes Betuncal | Everton | FWD | 100 | 0.310 | 22 |
| Armando Broja | Armando Broja | Everton | FWD | 100 | 0.310 | 22 |
| Mykhailo Mudryk | Mykhailo Mudryk | Chelsea | MID | 100 | 0.333 | 22 |
| Christopher Nkunku | Christopher Nkunku | Chelsea | MID | 100 | 0.449 | 22 |
| Federico Chiesa | Federico Chiesa | Liverpool | MID | 100 | 0.398 | 25 |
| Kai Havertz | Kai Havertz | Arsenal | FWD | 100 | 0.420 | 25 |
| Ismeal Kabia | Ismeal Kabia | Arsenal | MID | 100 | 0.313 | 25 |
| Nicolas Jackson | Nicolas Jackson | Chelsea | FWD | 100 | 0.385 | 25 |
| Jhon Durán | Jhon Durán | Aston Villa | FWD | 100 | 0.377 | 24 |
| Dominic Calvert-Lewin | Dominic Calvert-Lewin | Everton | FWD | 100 | 0.370 | 24 |
| Tyrique George | Tyrique George | Chelsea | MID | 100 | 0.305 | 24 |
| Jayden Danns | Jayden Danns | Liverpool | FWD | 100 | 0.342 | 24 |
| Federico Chiesa | Federico Chiesa | Liverpool | MID | 100 | 0.312 | 24 |
| Damola Ajayi | Damola Ajayi | Spurs | MID | 100 | 0.330 | 23 |
| James Maddison | James Maddison | Spurs | MID | 100 | 0.359 | 23 |
| Brennan Johnson | Brennan Johnson | Spurs | MID | 100 | 0.364 | 23 |
| Federico Chiesa | Federico Chiesa | Liverpool | MID | 100 | 0.368 | 16 |
| Tyrique George | Tyrique George | Chelsea | MID | 100 | 0.323 | 16 |
| Mykhailo Mudryk | Mykhailo Mudryk | Chelsea | MID | 100 | 0.309 | 16 |
| Danny Welbeck | Danny Welbeck | Brighton | FWD | 100 | 0.330 | 16 |
| Luis Sinisterra | Luis Sinisterra | Bournemouth | MID | 100 | 0.333 | 16 |
| Niclas Füllkrug | Niclas Füllkrug | West Ham | FWD | 100 | 0.371 | 15 |
| Michail Antonio | Michail Antonio | West Ham | FWD | 100 | 0.319 | 15 |
| Ethan Wheatley | Ethan Wheatley | Man Utd | FWD | 100 | 0.300 | 15 |
| Julio Enciso | Julio Enciso | Brighton | MID | 100 | 0.301 | 15 |
| Phil Foden | Phil Foden | Man City | MID | 100 | 0.315 | 15 |
| Erling Haaland | Erling Haaland | Man City | FWD | 100 | 0.460 | 26 |
| Diogo Jota | Diogo Teixeira da Silva | Liverpool | MID | 100 | 0.354 | 26 |
| Luis Sinisterra | Luis Sinisterra | Bournemouth | MID | 100 | 0.313 | 26 |
| Ismeal Kabia | Ismeal Kabia | Arsenal | MID | 100 | 0.309 | 26 |
| Niclas Füllkrug | Niclas Füllkrug | West Ham | FWD | 100 | 0.339 | 25 |
| Danny Ings | Danny Ings | West Ham | FWD | 100 | 0.308 | 25 |
| Dane Scarlett | Dane Scarlett | Spurs | FWD | 100 | 0.329 | 25 |
| Amad Diallo | Amad Diallo | Man Utd | MID | 100 | 0.321 | 25 |
| Dominic Sadi | Dominic Sadi | Bournemouth | MID | 100 | 0.312 | 25 |
| Harvey Elliott | Harvey Elliott | Liverpool | MID | 100 | 0.302 | 25 |
| Cody Gakpo | Cody Gakpo | Liverpool | FWD | 100 | 0.436 | 25 |
| Federico Chiesa | Federico Chiesa | Liverpool | MID | 100 | 0.423 | 28 |
| Cody Gakpo | Cody Gakpo | Liverpool | FWD | 100 | 0.460 | 28 |
| Jean-Philippe Mateta | Jean-Philippe Mateta | Crystal Palace | FWD | 100 | 0.455 | 28 |
| Noni Madueke | Noni Madueke | Chelsea | MID | 100 | 0.377 | 28 |
| Amad Diallo | Amad Diallo | Man Utd | MID | 100 | 0.317 | 27 |
| Federico Chiesa | Federico Chiesa | Liverpool | MID | 100 | 0.321 | 27 |
| Alexander Isak | Alexander Isak | Newcastle | FWD | 100 | 0.373 | 27 |
| Nicolas Jackson | Nicolas Jackson | Chelsea | FWD | 100 | 0.490 | 27 |
| Noni Madueke | Noni Madueke | Chelsea | MID | 100 | 0.357 | 27 |
| Crysencio Summerville | Crysencio Summerville | West Ham | MID | 100 | 0.308 | 27 |
| Danny Ings | Danny Ings | West Ham | FWD | 100 | 0.356 | 27 |
| Dane Scarlett | Dane Scarlett | Spurs | FWD | 100 | 0.302 | 27 |
| Danny Welbeck | Danny Welbeck | Brighton | FWD | 100 | 0.401 | 26 |
| William Osula | William Osula | Newcastle | FWD | 100 | 0.352 | 15 |
| Kadan Young | Kadan Young | Aston Villa | MID | 100 | 0.323 | 15 |
| Nicolas Jackson | Nicolas Jackson | Chelsea | FWD | 100 | 0.458 | 14 |
| Diogo Jota | Diogo Teixeira da Silva | Liverpool | MID | 100 | 0.345 | 14 |
| Phil Foden | Phil Foden | Man City | MID | 100 | 0.361 | 14 |
| Beto | Norberto Bercique Gomes Betuncal | Everton | FWD | 100 | 0.301 | 14 |
| Mikey Moore | Mikey Moore | Spurs | MID | 100 | 0.312 | 13 |
| Christopher Nkunku | Christopher Nkunku | Chelsea | MID | 100 | 0.401 | 30 |
| Chris Wood | Chris Wood | Nott'm Forest | FWD | 100 | 0.427 | 30 |
| Dominic Sadi | Dominic Sadi | Bournemouth | MID | 100 | 0.331 | 30 |
| Marcus Tavernier | Marcus Tavernier | Bournemouth | MID | 100 | 0.307 | 30 |
| Luis Sinisterra | Luis Sinisterra | Bournemouth | MID | 100 | 0.369 | 30 |
| Justin Kluivert | Justin Kluivert | Bournemouth | MID | 100 | 0.432 | 30 |
| Dominic Calvert-Lewin | Dominic Calvert-Lewin | Everton | FWD | 100 | 0.323 | 29 |
| Dominic Calvert-Lewin | Dominic Calvert-Lewin | Everton | FWD | 100 | 0.314 | 28 |
| Anthony Gordon | Anthony Gordon | Newcastle | MID | 100 | 0.345 | 28 |
| William Osula | William Osula | Newcastle | FWD | 100 | 0.304 | 28 |
| Dane Scarlett | Dane Scarlett | Spurs | FWD | 100 | 0.317 | 28 |
| Mikey Moore | Mikey Moore | Spurs | MID | 100 | 0.321 | 31 |
| Timo Werner | Timo Werner | Spurs | MID | 100 | 0.346 | 31 |
| Dane Scarlett | Dane Scarlett | Spurs | FWD | 100 | 0.406 | 31 |
| Anthony Gordon | Anthony Gordon | Newcastle | MID | 100 | 0.345 | 31 |
| Taiwo Awoniyi | Taiwo Awoniyi | Nott'm Forest | FWD | 100 | 0.313 | 31 |
| Chris Wood | Chris Wood | Nott'm Forest | FWD | 100 | 0.366 | 31 |
| Anthony Gordon | Anthony Gordon | Newcastle | MID | 100 | 0.400 | 30 |
| William Osula | William Osula | Newcastle | FWD | 100 | 0.316 | 30 |
| Erling Haaland | Erling Haaland | Man City | FWD | 100 | 0.658 | 30 |
| Kevin De Bruyne | Kevin De Bruyne | Man City | MID | 100 | 0.316 | 30 |
| Phil Foden | Phil Foden | Man City | MID | 100 | 0.460 | 30 |
| Federico Chiesa | Federico Chiesa | Liverpool | MID | 100 | 0.304 | 30 |
| Danny Ings | Danny Ings | West Ham | FWD | 100 | 0.363 | 33 |
| Son Heung-Min | Son Heung-min | Spurs | MID | 100 | 0.306 | 33 |
| Federico Chiesa | Federico Chiesa | Liverpool | MID | 100 | 0.355 | 33 |
| Taiwo Awoniyi | Taiwo Awoniyi | Nott'm Forest | FWD | 100 | 0.354 | 32 |
| William Osula | William Osula | Newcastle | FWD | 100 | 0.309 | 32 |
| Phil Foden | Phil Foden | Man City | MID | 100 | 0.349 | 32 |
| Federico Chiesa | Federico Chiesa | Liverpool | MID | 100 | 0.338 | 32 |
| Justin Kluivert | Justin Kluivert | Bournemouth | MID | 100 | 0.318 | 32 |
| Justin Kluivert | Justin Kluivert | Bournemouth | MID | 100 | 0.321 | 31 |
| Damola Ajayi | Damola Ajayi | Spurs | MID | 100 | 0.364 | 31 |
| Dejan Kulusevski | Dejan Kulusevski | Spurs | MID | 100 | 0.342 | 31 |
| Taiwo Awoniyi | Taiwo Awoniyi | Nott'm Forest | FWD | 100 | 0.410 | 13 |
| Ethan Wheatley | Ethan Wheatley | Man Utd | FWD | 100 | 0.321 | 13 |
| Rasmus Højlund | Rasmus Højlund | Man Utd | FWD | 100 | 0.376 | 13 |
| Diogo Jota | Diogo Teixeira da Silva | Liverpool | MID | 100 | 0.343 | 13 |
| William Osula | William Osula | Newcastle | FWD | 100 | 0.312 | 13 |
| Julio Enciso | Julio Enciso | Brighton | MID | 100 | 0.362 | 13 |
| Federico Chiesa | Federico Chiesa | Liverpool | MID | 100 | 0.375 | 12 |
| Diogo Jota | Diogo Teixeira da Silva | Liverpool | MID | 100 | 0.449 | 12 |
| William Osula | William Osula | Newcastle | FWD | 100 | 0.408 | 12 |
| James McAtee | James McAtee | Man City | MID | 100 | 0.303 | 12 |
| Ethan Wheatley | Ethan Wheatley | Man Utd | FWD | 100 | 0.331 | 12 |
| Oscar Bobb | Oscar Bobb | Man City | MID | 100 | 0.310 | 35 |
| Facundo Buonanotte | Facundo Buonanotte | Leicester | MID | 100 | 0.302 | 35 |
| Stephy Mavididi | Stephy Mavididi | Leicester | MID | 100 | 0.319 | 35 |
| Martin Sherif | Martin Sherif | Everton | FWD | 100 | 0.364 | 35 |
| Armando Broja | Armando Broja | Everton | FWD | 100 | 0.393 | 35 |
| Taiwo Awoniyi | Taiwo Awoniyi | Nott'm Forest | FWD | 100 | 0.315 | 35 |
| Christopher Nkunku | Christopher Nkunku | Chelsea | MID | 100 | 0.332 | 35 |
| Hwang Hee-Chan | Hwang Hee-chan | Wolves | MID | 100 | 0.350 | 34 |
| Federico Chiesa | Federico Chiesa | Liverpool | MID | 100 | 0.384 | 34 |
| Christopher Nkunku | Christopher Nkunku | Chelsea | MID | 100 | 0.357 | 34 |
| Dominic Sadi | Dominic Sadi | Bournemouth | MID | 100 | 0.308 | 34 |
| Luis Sinisterra | Luis Sinisterra | Bournemouth | MID | 100 | 0.320 | 34 |
| Phil Foden | Phil Foden | Man City | MID | 100 | 0.331 | 33 |
| Armando Broja | Armando Broja | Everton | FWD | 100 | 0.411 | 37 |
| Christopher Nkunku | Christopher Nkunku | Chelsea | MID | 100 | 0.370 | 37 |
| Diogo Jota | Diogo Teixeira da Silva | Liverpool | MID | 100 | 0.308 | 37 |
| Alexander Isak | Alexander Isak | Newcastle | FWD | 100 | 0.357 | 37 |
| Oscar Bobb | Oscar Bobb | Man City | MID | 100 | 0.397 | 36 |
| Jack Grealish | Jack Grealish | Man City | MID | 100 | 0.317 | 36 |
| Danny Ings | Danny Ings | West Ham | FWD | 100 | 0.341 | 35 |
| Armando Broja | Armando Broja | Everton | FWD | 100 | 0.301 | 12 |
| Ismeal Kabia | Ismeal Kabia | Arsenal | MID | 100 | 0.312 | 12 |
| Kai Havertz | Kai Havertz | Arsenal | FWD | 100 | 0.394 | 12 |
| Hwang Hee-Chan | Hwang Hee-chan | Wolves | MID | 100 | 0.364 | 11 |
| Niclas Füllkrug | Niclas Füllkrug | West Ham | FWD | 100 | 0.333 | 11 |
| Mikey Moore | Mikey Moore | Spurs | MID | 100 | 0.394 | 11 |
| Callum Wilson | Callum Wilson | Newcastle | FWD | 100 | 0.308 | 11 |
| Ethan Wheatley | Ethan Wheatley | Man Utd | FWD | 100 | 0.378 | 11 |
| Diogo Jota | Diogo Teixeira da Silva | Liverpool | MID | 100 | 0.417 | 11 |
| Federico Chiesa | Federico Chiesa | Liverpool | MID | 100 | 0.308 | 11 |
| Mikey Moore | Mikey Moore | Spurs | MID | 100 | 0.303 | 10 |
| Christopher Nkunku | Christopher Nkunku | Chelsea | MID | 100 | 0.350 | 10 |

## 2025-26

- **Match rate:** 15,620 of 15,805 priced name-rows (98.83%) across 380 fixtures; 39 distinct unmatched names (185 rows), left null.
- **Provenance:** exact 12,313, token_subset 2,193, club+token 979, fuzzy 78, manual 57. Distinct fuzzy pairs 3, surname-token pairs 34, token-subset pairs 79 (all listed below); manual entries 3 names / 57 rows (table below), manual conflicts 0, manual entries refused because the element was not at a fixture club that gameweek 0.
- **assert_crosswalk_unique:** 2,038 per-book boards asserted (no element claimed twice, no name mapped twice), 0 raised.

**Manual entries applied (evidence recorded in `match_evidence`; each auditable without this session):**

| book name | → FPL name (element) | rows | evidence |
|---|---|---|---|
| Chidozie Obi | Chido Obi (467) | 10 | Chido Obi | Man Utd GW1-38, FWD, 0 min / 0 goals | Chidozie Obi-Martin; the only Obi at Man Utd; priced on 10 Man Utd boards at 0.31 mean implied despite 0 minutes (placeholder-price case, identification certain) |
| Edward Nketiah | Eddie Nketiah (284) | 24 | Eddie Nketiah | Crystal Palace GW1-38, FWD, 414 min / 2 goals | Edward Keddar Nketiah; the only Nketiah at Palace; the given-name rule rejected edward/eddie (ratio < 60) -- correct to refuse automatically, certain here |
| Lucas Paqueta | Lucas Tolentino Coelho de Lima (612) | 23 | Lucas Tolentino Coelho de Lima | West Ham GW1-38, MID, 1513 min / 4 goals | as 2024-25: the only Lucas at West Ham (Digne Villa, Pires Silva Burnley, Bergvall Spurs are club-excluded) |
- **Uniqueness:** per-book board violations 0; cross-book multi-spellings of one element 28 (e.g. "Josh King" / "Joshua King" — the consensus must merge by element, not by string); cross-fixture name→element inconsistencies 0.
- **Placeholder prices:** 205 matched rows (35 players) with < 90 season minutes priced at mean implied ≥ 0.25 — youth/fringe names carried on boards at short prices; a data-quality item for the de-vig step, not a matching error.
- **Team audit:** 0 matched rows whose element's club is not in the fixture.
- **Homonyms:** 0 exact-matched names that also exist at another club this season (listed).
- **Plausibility flags:** 0 price/position (GK ≥ .15 or DEF ≥ .35 mean implied), 347 price/minutes (played 0 with mean implied ≥ .30).
- **Outfield starters not covered:** 44 players / 254 player-fixtures / 20,946 minutes of 614,693 outfield starter minutes in priced fixtures → outfield starter coverage **96.49%**. Split: **unpriced** (no candidate name on the board) 239 player-fixtures; **unmatched with a candidate name** 0 player-fixtures across 0 players — the manual-pass list below. Goalkeepers are not priced on these boards (39 GKs, 69,873 minutes) and are excluded.

**Top uncovered OUTFIELD starters by minutes (played ≥60 in a priced fixture, no book name mapped to them; mostly unpriced):**

| player | team | pos | fixtures | minutes |
|---|---|---|---|---|
| Pascal Groß | Brighton | MID | 20 | 1797 |
| Antoine Semenyo | Man City | MID | 19 | 1622 |
| Marc Guéhi | Man City | DEF | 17 | 1530 |
| Valentín Castellanos | West Ham | FWD | 17 | 1339 |
| Adam Armstrong | Wolves | FWD | 15 | 1262 |
| Axel Disasi | West Ham | DEF | 14 | 1254 |
| Rayan Vitor Simplício Rocha | Bournemouth | MID | 14 | 1142 |
| Lisandro Martínez | Man Utd | DEF | 12 | 1077 |
| Conor Gallagher | Spurs | MID | 13 | 1073 |
| Brennan Johnson | Crystal Palace | MID | 13 | 1031 |
| James Ward-Prowse | Burnley | MID | 9 | 755 |
| Pablo Felipe Pereira de Jesus | West Ham | FWD | 9 | 686 |
| Jørgen Strand Larsen | Crystal Palace | FWD | 9 | 652 |
| Douglas Luiz Soares de Paulo | Aston Villa | MID | 6 | 469 |
| Chadi Riad Dnanou | Crystal Palace | DEF | 6 | 459 |
| Radu Drăgușin | Spurs | DEF | 5 | 449 |
| Nilson Angulo | Sunderland | MID | 5 | 371 |
| Angel Gomes | Wolves | MID | 5 | 357 |
| Oscar Bobb | Fulham | MID | 5 | 345 |
| Oleksandr Zinchenko | Nott'm Forest | DEF | 4 | 343 |

**Unmatched WITH a candidate name — the proposed MANUAL pass (not applied; each needs club + position + minutes evidence):**

| FPL name | team | pos | book name(s) on the board | fixtures | minutes |
|---|---|---|---|---|---|

**Unmatched book names, by mean implied probability (top 25 of 39):**

| book name | fixture (first) | books | mean implied | best candidate score |
|---|---|---|---|---|
| Trent Toure Kone-Doherty | GW22 Liverpool v Burnley | 2 | 0.294 | unmatched(best=50,runner=49) |
| Ryan Kavuma-McQueen | GW35 Chelsea v Nott'm Forest | 1 | 0.292 | unmatched(best=57,runner=45) |
| Max Dowman | GW1 Man Utd v Arsenal | 3 | 0.278 | unmatched(best=48,runner=48) |
| Brennan Johnson | GW20 Spurs v Sunderland | 1 | 0.250 | unmatched(best=78,runner=59) |
| Harry Gray | GW1 Leeds v Everton | 4 | 0.247 | unmatched(best=67,runner=43) |
| Facundo Buonanotte | GW22 Chelsea v Brentford | 1 | 0.233 | unmatched(best=50,runner=44) |
| Zyan Blake | GW36 Nott'm Forest v Newcastle | 1 | 0.227 | unmatched(best=55,runner=50) |
| Ben Hammond | GW24 Nott'm Forest v Crystal Palace | 2 | 0.222 | unmatched(best=54,runner=52) |
| Mateus Mane | GW3 Wolves v Everton | 5 | 0.220 | unmatched(best=61,runner=58) |
| Jimmy Sinclair | GW33 Nott'm Forest v Burnley | 4 | 0.218 | unmatched(best=48,runner=44) |
| Tynan Thompson | GW23 Burnley v Spurs | 4 | 0.214 | unmatched(best=57,runner=50) |
| Reece Munro | GW3 Man Utd v Burnley | 2 | 0.211 | unmatched(best=48,runner=44) |
| Jacob Ramsey | GW3 Aston Villa v Crystal Palace | 1 | 0.200 | unmatched(best=46,runner=44) |
| Luca Williams-Barnett | GW16 Nott'm Forest v Spurs | 2 | 0.200 | unmatched(best=76,runner=51) |
| Jack Thompson | GW14 Wolves v Nott'm Forest | 2 | 0.200 | unmatched(best=52,runner=48) |
| Reggie Walsh | GW27 Chelsea v Burnley | 2 | 0.182 | unmatched(best=44,runner=43) |
| Archie Whitehall | GW14 Wolves v Nott'm Forest | 2 | 0.167 | unmatched(best=47,runner=45) |
| Seth Ky Ridgeon | GW12 Fulham v Sunderland | 2 | 0.160 | unmatched(best=52,runner=48) |
| Travis Patterson | GW1 Aston Villa v Newcastle | 2 | 0.154 | unmatched(best=53,runner=48) |
| Douglas Luiz de Paulo | GW24 Nott'm Forest v Crystal Palace | 1 | 0.154 | unmatched(best=49,runner=48) |
| Justin Clarke | GW4 Everton v Aston Villa | 2 | 0.148 | unmatched(best=50,runner=48) |
| Aidan Borland | GW13 Aston Villa v Wolves | 2 | 0.143 | unmatched(best=58,runner=52) |
| Alfie Harrison | GW1 Aston Villa v Newcastle | 4 | 0.141 | unmatched(best=73,runner=52) |
| Samuel Rak-Sakyi | GW2 West Ham v Chelsea | 2 | 0.138 | unmatched(best=50,runner=50) |
| Rhys Chadwick-Chaplin | GW1 Leeds v Everton | 2 | 0.132 | unmatched(best=44,runner=42) |

**Fuzzy matches (ALL — where silent errors live): 3**

| book name | → FPL name | team | pos | score | mean implied | gw |
|---|---|---|---|---|---|---|
| Ferdi Kadioglu | Ferdi Kadıoğlu | Brighton | DEF | 93 | 0.161 | 1 |
| Rasmus Hojlund | Rasmus Højlund | Man Utd | FWD | 93 | 0.233 | 1 |
| Mickey van de Ven | Micky van de Ven | Spurs | DEF | 97 | 0.103 | 1 |

**Discriminating-token matches (ALL): 34**

| book name | → FPL name | team | pos | score | mean implied | gw |
|---|---|---|---|---|---|---|
| Ibrahim Konate | Ibrahima Konaté | Liverpool | DEF | 90 | 0.100 | 1 |
| Valentino Livramento | Tino Livramento | Newcastle | DEF | 90 | 0.079 | 1 |
| Matthew O'Riley | Matt O'Riley | Brighton | MID | 90 | 0.269 | 1 |
| Max Kilman | Maximilian Kilman | West Ham | DEF | 90 | 0.070 | 1 |
| Andrew Irving | Andy Irving | West Ham | MID | 90 | 0.195 | 1 |
| Oliver Scarles | Ollie Scarles | West Ham | DEF | 90 | 0.085 | 1 |
| Christopher Rigg | Chris Rigg | Sunderland | MID | 90 | 0.242 | 1 |
| Daniel Neil | Dan Neil | Sunderland | MID | 90 | 0.121 | 1 |
| Jeanricner Bellegarde | Jean-Ricner Bellegarde | Wolves | MID | 90 | 0.134 | 1 |
| Tijani Reijnders | Tijjani Reijnders | Man City | MID | 90 | 0.258 | 1 |
| David Moller Wolfe | David Møller Wolfe | Wolves | DEF | 90 | 0.071 | 1 |
| Nicolas Gonzalez Iglesias | Nico González Iglesias | Man City | MID | 90 | 0.154 | 1 |
| Niko O'Reilly | Nico O'Reilly | Man City | DEF | 90 | 0.182 | 1 |
| Fernando Lopez Gonzalez | Fer López González | Wolves | MID | 90 | 0.203 | 1 |
| Jorgen Strand Larsen | Jørgen Strand Larsen | Wolves | FWD | 90 | 0.239 | 1 |
| Joshua Kofi Acheampong | Josh Acheampong | Chelsea | DEF | 90 | 0.121 | 1 |
| Carlos Casemiro | Carlos Henrique Casimiro | Man Utd | MID | 90 | 0.116 | 1 |
| Alexander Zinchenko | Oleksandr Zinchenko | Arsenal | DEF | 90 | 0.125 | 1 |
| Martin Odegaard | Martin Ødegaard | Arsenal | MID | 90 | 0.217 | 1 |
| Ben White | Benjamin White | Arsenal | DEF | 90 | 0.096 | 1 |
| Christian Norgaard | Christian Nørgaard | Arsenal | MID | 90 | 0.139 | 1 |
| Vitaliy Mykolenko | Vitalii Mykolenko | Everton | DEF | 90 | 0.055 | 1 |
| Brendan Aaronson | Brenden Aaronson | Leeds | MID | 90 | 0.216 | 1 |
| Iliya Gruev | Ilia Gruev | Leeds | MID | 90 | 0.115 | 1 |
| Nazariy Rusyn | Nazarii Rusyn | Sunderland | FWD | 90 | 0.198 | 2 |
| Julio Cesar Enciso | Julio Enciso Espínola | Brighton | MID | 90 | 0.308 | 2 |
| Joshua King | Josh King | Fulham | MID | 90 | 0.282 | 2 |
| Joseph Willock | Joe Willock | Newcastle | MID | 90 | 0.154 | 2 |
| Ajibola Alese | Aji Alese | Sunderland | DEF | 90 | 0.035 | 4 |
| Yeremi Pino | Yéremy Pino Santos | Crystal Palace | MID | 90 | 0.226 | 4 |
| Chrisantus Uche | Christantus Uche | Crystal Palace | FWD | 90 | 0.268 | 4 |
| Toluwalase Emmanuel Arokodare | Tolu Arokodare | Wolves | FWD | 90 | 0.200 | 4 |
| Alejandro Jimenez | Álex Jiménez Sánchez | Bournemouth | DEF | 90 | 0.117 | 12 |
| Sam Amissah | Samuel Amissah | Fulham | DEF | 90 | 0.072 | 12 |

**Token-subset matches (ALL): 79**

| book name | → FPL name | team | pos | score | mean implied | gw |
|---|---|---|---|---|---|---|
| Wataru Endo | Endo Wataru | Liverpool | MID | 95 | 0.179 | 1 |
| Julian Araujo | Julián Araujo Zúñiga | Bournemouth | DEF | 95 | 0.059 | 1 |
| Marcos Senesi | Marcos Senesi Barón | Bournemouth | DEF | 95 | 0.074 | 1 |
| Julio Soler | Julio Soler Barreto | Bournemouth | DEF | 95 | 0.039 | 1 |
| Eli Junior Kroupi | Junior Kroupi | Bournemouth | FWD | 95 | 0.281 | 1 |
| Ben Doak | Ben Gannon-Doak | Liverpool | MID | 95 | 0.303 | 1 |
| Ezri Konsa | Ezri Konsa Ngoyo | Aston Villa | DEF | 95 | 0.087 | 1 |
| Joelinton | Joelinton Cássio Apolinário de Lira | Newcastle | MID | 95 | 0.212 | 1 |
| Alex Moreno | Álex Moreno Lopera | Aston Villa | DEF | 95 | 0.081 | 1 |
| Bruno Guimaraes | Bruno Guimarães Rodriguez Moura | Newcastle | MID | 95 | 0.142 | 1 |
| Samuel Iling | Samuel Iling-Junior | Aston Villa | MID | 95 | 0.242 | 1 |
| Raul Jimenez | Raúl Jiménez Rodríguez | Fulham | FWD | 95 | 0.314 | 1 |
| Andreas Pereira | Andreas Hoelgebaum Pereira | Fulham | MID | 95 | 0.189 | 1 |
| Igor Julio | Igor Julio dos Santos de Paulo | Brighton | DEF | 95 | 0.063 | 1 |
| Kaoru Mitoma | Mitoma Kaoru | Brighton | MID | 95 | 0.317 | 1 |
| Rodrigo Muniz | Rodrigo Muniz Carvalho | Fulham | FWD | 95 | 0.289 | 1 |
| Carlos Baleba Noom Quomah | Carlos Baleba | Brighton | MID | 95 | 0.177 | 1 |
| Diego Alexander Gomez Amarilla | Diego Gómez Amarilla | Brighton | MID | 95 | 0.218 | 1 |
| Fabio Carvalho | Fábio Freitas Gouveia Carvalho | Brentford | MID | 95 | 0.211 | 1 |
| Jair Cunha | Jair Paula da Cunha Filho | Nott'm Forest | DEF | 95 | 0.092 | 1 |
| Murillo Santiago Costa dos Santos | Murillo Costa dos Santos | Nott'm Forest | DEF | 95 | 0.086 | 1 |
| David Carmo | David Mota Veiga Teixeira do Carmo | Nott'm Forest | DEF | 95 | 0.094 | 1 |
| Joao Pedro Ferreira Silva | João Pedro Ferreira da Silva | Nott'm Forest | MID | 95 | 0.250 | 1 |
| Eric Moreira | Eric da Silva Moreira | Nott'm Forest | MID | 95 | 0.167 | 1 |
| Edson Alvarez | Edson Álvarez Velázquez | West Ham | MID | 95 | 0.129 | 1 |
| Ian Poveda | Ian Poveda-Ocampo | Sunderland | MID | 95 | 0.154 | 1 |
| Eliezer Mayenda | Eliezer Mayenda Dossou | Sunderland | FWD | 95 | 0.263 | 1 |
| El Hadji Diouf | El Hadji Malick Diouf | West Ham | DEF | 95 | 0.147 | 1 |
| Dominic Solanke | Dominic Solanke-Mitchell | Spurs | FWD | 95 | 0.463 | 1 |
| Pape Sarr | Pape Matar Sarr | Spurs | MID | 95 | 0.237 | 1 |
| Pedro Porro | Pedro Porro Sauceda | Spurs | DEF | 95 | 0.145 | 1 |
| Louis Jordan Beyer | Jordan Beyer | Burnley | DEF | 95 | 0.059 | 1 |
| Mike Ndayishimiye | Mike Trésor Ndayishimiye | Burnley | MID | 95 | 0.182 | 1 |
| Lucas Pires | Lucas Pires Silva | Burnley | DEF | 95 | 0.081 | 1 |
| Ruben Dias | Rúben dos Santos Gato Alves Dias | Man City | DEF | 95 | 0.103 | 1 |
| Bernardo Silva | Bernardo Mota Veiga de Carvalho e Silva | Man City | MID | 95 | 0.198 | 1 |
| Matheus Luiz Nunes | Matheus Nunes | Man City | DEF | 95 | 0.145 | 1 |
| Erling Braut Haaland | Erling Haaland | Man City | FWD | 95 | 0.579 | 1 |
| Santiago Ignacio Bueno Sciutto | Santiago Ignacio Bueno | Wolves | DEF | 95 | 0.071 | 1 |
| Cardoso Pedro Lima | Pedro Cardoso de Lima | Wolves | DEF | 95 | 0.088 | 1 |
| Pedro Neto | Pedro Lomba Neto | Chelsea | MID | 95 | 0.280 | 1 |
| Marc Cucurella | Marc Cucurella Saseta | Chelsea | DEF | 95 | 0.136 | 1 |
| Jefferson Lerma | Jefferson Lerma Solís | Crystal Palace | MID | 95 | 0.088 | 1 |
| Moises Caicedo | Moisés Caicedo Corozo | Chelsea | MID | 95 | 0.110 | 1 |
| Daniel Munoz | Daniel Muñoz Mejía | Crystal Palace | DEF | 95 | 0.133 | 1 |
| Dario Essugo | Dário Luís Essugo | Chelsea | MID | 95 | 0.132 | 1 |
| Andrey Santos | Andrey Nascimento dos Santos | Chelsea | MID | 95 | 0.260 | 1 |
| Jamie Jermaine Bynoe-Gittens | Jamie Bynoe-Gittens | Chelsea | MID | 95 | 0.289 | 1 |
| Estevao Oliveira Goncalves | Estêvão Almeida de Oliveira Gonçalves | Chelsea | MID | 95 | 0.372 | 1 |
| Diego Leon | Diego León Blanco | Man Utd | DEF | 95 | 0.075 | 1 |
| Bruno Fernandes | Bruno Borges Fernandes | Man Utd | MID | 95 | 0.235 | 1 |
| Mikel Merino | Mikel Merino Zazón | Arsenal | MID | 95 | 0.290 | 1 |
| Diogo Dalot | Diogo Dalot Teixeira | Man Utd | DEF | 95 | 0.102 | 1 |
| Magalhaes Gabriel | Gabriel dos Santos Magalhães | Arsenal | DEF | 95 | 0.119 | 1 |
| Matheus Cunha | Matheus Santos Carneiro da Cunha | Man Utd | MID | 95 | 0.265 | 1 |
| Gabriel Martinelli | Gabriel Martinelli Silva | Arsenal | MID | 95 | 0.281 | 1 |
| Manuel Ugarte | Manuel Ugarte Ribeiro | Man Utd | MID | 95 | 0.102 | 1 |
| Iliman-Cheikh Ndiaye | Iliman Ndiaye | Everton | MID | 95 | 0.251 | 1 |
| Ao Tanaka | Tanaka Ao | Leeds | MID | 95 | 0.142 | 1 |
| Carlos Alcaraz | Carlos Alcaraz Durán | Everton | MID | 95 | 0.207 | 1 |
| Degnand Wilfried Gnonto | Wilfried Gnonto | Leeds | MID | 95 | 0.253 | 1 |
| Youssef Chermiti | Youssef Ramalho Chermiti | Everton | FWD | 95 | 0.238 | 1 |
| Hugo Bueno | Hugo Bueno López | Wolves | DEF | 95 | 0.079 | 2 |
| Yerson Mosquera | Yerson Mosquera Valdelamar | Wolves | DEF | 95 | 0.064 | 2 |
| Edmond-Paris Maghoma | Paris Maghoma | Brentford | MID | 95 | 0.111 | 2 |
| Ogochukwu Onyeka Frank | Frank Onyeka | Brentford | MID | 95 | 0.147 | 2 |
| Marc Guiu | Marc Guiu Paz | Sunderland | FWD | 95 | 0.229 | 2 |
| Naouirou Mohamed Ahamada | Naouirou Ahamada | Crystal Palace | MID | 95 | 0.108 | 2 |
| Rodri | Rodrigo 'Rodri' Hernandez Cascante | Man City | MID | 95 | 0.178 | 2 |
| Joao Palhinha | João Maria Lobo Alves Palhares Costa Palhinha Gonçalves | Spurs | MID | 95 | 0.118 | 2 |
| Iyenoma Destiny Udogie | Destiny Udogie | Spurs | DEF | 95 | 0.077 | 2 |
| Kota Takai | Takai Kōta | Spurs | DEF | 95 | 0.058 | 2 |
| Omari Giraud-Hutchinson | Omari Hutchinson | Nott'm Forest | MID | 95 | 0.250 | 3 |
| Douglas Luiz de Paulo | Douglas Luiz Soares de Paulo | Nott'm Forest | MID | 95 | 0.173 | 3 |
| Alejandro Garnacho | Alejandro Garnacho Ferreyra | Chelsea | MID | 95 | 0.297 | 4 |
| Florentino Luis | Florentino Ibrain Morris Luís | Burnley | MID | 95 | 0.044 | 4 |
| Mateus Fernandes | Mateus Gonçalo Espanha Fernandes | West Ham | MID | 95 | 0.167 | 4 |
| Seth Ky Ridgeon | Seth Ridgeon | Fulham | MID | 95 | 0.160 | 18 |
| Rhys Chadwick-Chaplin | Rhys Chadwick | Leeds | MID | 95 | 0.156 | 37 |

**Exact matches with a same-name player at another club (homonyms): 0**


**Price/position flags: 0**


**Price/minutes flags: 344**

| book name | → FPL name | team | pos | score | mean implied | gw |
|---|---|---|---|---|---|---|
| Matthew O'Riley | Matt O'Riley | Brighton | MID | 90 | 0.305 | 36 |
| Chrisantus Uche | Christantus Uche | Crystal Palace | FWD | 90 | 0.302 | 27 |
| Julio Cesar Enciso | Julio Enciso Espínola | Brighton | MID | 90 | 0.308 | 2 |
| Rasmus Hojlund | Rasmus Højlund | Man Utd | FWD | 93 | 0.315 | 2 |
| Rasmus Hojlund | Rasmus Højlund | Man Utd | FWD | 93 | 0.455 | 3 |
| Erling Braut Haaland | Erling Haaland | Man City | FWD | 95 | 0.603 | 38 |
| Dominic Solanke | Dominic Solanke-Mitchell | Spurs | FWD | 95 | 0.396 | 3 |
| Ben Doak | Ben Gannon-Doak | Liverpool | MID | 95 | 0.303 | 1 |
| Eli Junior Kroupi | Junior Kroupi | Bournemouth | FWD | 95 | 0.353 | 4 |
| Dominic Solanke | Dominic Solanke-Mitchell | Spurs | FWD | 95 | 0.337 | 35 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.352 | 35 |
| Diego Alexander Gomez Amarilla | Diego Gómez Amarilla | Brighton | MID | 95 | 0.361 | 36 |
| Raul Jimenez | Raúl Jiménez Rodríguez | Fulham | FWD | 95 | 0.423 | 36 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.310 | 32 |
| Matheus Cunha | Matheus Santos Carneiro da Cunha | Man Utd | MID | 95 | 0.340 | 34 |
| Dominic Solanke | Dominic Solanke-Mitchell | Spurs | FWD | 95 | 0.378 | 38 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.395 | 30 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.340 | 31 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.303 | 29 |
| Erling Braut Haaland | Erling Haaland | Man City | FWD | 95 | 0.594 | 28 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.390 | 26 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.461 | 27 |
| Estevao Oliveira Goncalves | Estêvão Almeida de Oliveira Gonçalves | Chelsea | MID | 95 | 0.400 | 27 |
| Estevao Oliveira Goncalves | Estêvão Almeida de Oliveira Gonçalves | Chelsea | MID | 95 | 0.302 | 25 |
| Alejandro Garnacho | Alejandro Garnacho Ferreyra | Chelsea | MID | 95 | 0.334 | 27 |
| Jamie Jermaine Bynoe-Gittens | Jamie Bynoe-Gittens | Chelsea | MID | 95 | 0.347 | 27 |
| Dominic Solanke | Dominic Solanke-Mitchell | Spurs | FWD | 95 | 0.362 | 4 |
| Eli Junior Kroupi | Junior Kroupi | Bournemouth | FWD | 95 | 0.308 | 5 |
| Alejandro Garnacho | Alejandro Garnacho Ferreyra | Chelsea | MID | 95 | 0.301 | 6 |
| Eliezer Mayenda | Eliezer Mayenda Dossou | Sunderland | FWD | 95 | 0.306 | 24 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.367 | 25 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.325 | 38 |
| Gabriel Martinelli | Gabriel Martinelli Silva | Arsenal | MID | 95 | 0.304 | 23 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.322 | 23 |
| Estevao Oliveira Goncalves | Estêvão Almeida de Oliveira Gonçalves | Chelsea | MID | 95 | 0.353 | 24 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.423 | 24 |
| Estevao Oliveira Goncalves | Estêvão Almeida de Oliveira Gonçalves | Chelsea | MID | 95 | 0.308 | 22 |
| Dominic Solanke | Dominic Solanke-Mitchell | Spurs | FWD | 95 | 0.417 | 6 |
| Eli Junior Kroupi | Junior Kroupi | Bournemouth | FWD | 95 | 0.302 | 7 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.356 | 22 |
| Iliman-Cheikh Ndiaye | Iliman Ndiaye | Everton | MID | 95 | 0.308 | 20 |
| Iliman-Cheikh Ndiaye | Iliman Ndiaye | Everton | MID | 95 | 0.347 | 21 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.306 | 21 |
| Gabriel Martinelli | Gabriel Martinelli Silva | Arsenal | MID | 95 | 0.324 | 19 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.397 | 19 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.336 | 18 |
| Dominic Solanke | Dominic Solanke-Mitchell | Spurs | FWD | 95 | 0.364 | 15 |
| Dominic Solanke | Dominic Solanke-Mitchell | Spurs | FWD | 95 | 0.400 | 8 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.334 | 16 |
| Dominic Solanke | Dominic Solanke-Mitchell | Spurs | FWD | 95 | 0.308 | 14 |
| Kaoru Mitoma | Mitoma Kaoru | Brighton | MID | 95 | 0.334 | 15 |
| Eli Junior Kroupi | Junior Kroupi | Bournemouth | FWD | 95 | 0.358 | 15 |
| Dominic Solanke | Dominic Solanke-Mitchell | Spurs | FWD | 95 | 0.364 | 13 |
| Dominic Solanke | Dominic Solanke-Mitchell | Spurs | FWD | 95 | 0.323 | 9 |
| Gabriel Martinelli | Gabriel Martinelli Silva | Arsenal | MID | 95 | 0.348 | 10 |
| Matheus Cunha | Matheus Santos Carneiro da Cunha | Man Utd | MID | 95 | 0.364 | 12 |
| Dominic Solanke | Dominic Solanke-Mitchell | Spurs | FWD | 95 | 0.355 | 10 |
| Dominic Solanke | Dominic Solanke-Mitchell | Spurs | FWD | 95 | 0.372 | 11 |
| Estevao Oliveira Goncalves | Estêvão Almeida de Oliveira Gonçalves | Chelsea | MID | 95 | 0.312 | 12 |
| Alejandro Garnacho | Alejandro Garnacho Ferreyra | Chelsea | MID | 95 | 0.301 | 12 |
| Mikel Merino | Mikel Merino Zazón | Arsenal | MID | 95 | 0.384 | 2 |
| Gabriel Martinelli | Gabriel Martinelli Silva | Arsenal | MID | 95 | 0.364 | 2 |
| Marc Guiu | Marc Guiu Paz | Chelsea | FWD | 95 | 0.365 | 37 |
| Dominic Solanke | Dominic Solanke-Mitchell | Spurs | FWD | 95 | 0.343 | 37 |
| Estevao Oliveira Goncalves | Estêvão Almeida de Oliveira Gonçalves | Chelsea | MID | 95 | 0.308 | 37 |
| Alexander Isak | Alexander Isak | Liverpool | FWD | 100 | 0.480 | 38 |
| Jonah Kusi-Asare | Jonah Kusi-Asare | Fulham | FWD | 100 | 0.339 | 38 |
| Anthony Gordon | Anthony Gordon | Newcastle | MID | 100 | 0.309 | 38 |
| Bukayo Saka | Bukayo Saka | Arsenal | MID | 100 | 0.301 | 38 |
| Armando Broja | Armando Broja | Burnley | FWD | 100 | 0.331 | 38 |
| Benjamin Sesko | Benjamin Sesko | Man Utd | FWD | 100 | 0.331 | 38 |
| Jonah Kusi-Asare | Jonah Kusi-Asare | Fulham | FWD | 100 | 0.332 | 37 |
| Anthony Gordon | Anthony Gordon | Newcastle | MID | 100 | 0.339 | 37 |
| Benjamin Sesko | Benjamin Sesko | Man Utd | FWD | 100 | 0.450 | 37 |
| Joao Pedro Junqueira de Jesus | João Pedro Junqueira de Jesus | Chelsea | FWD | 100 | 0.440 | 37 |
| Alexander Isak | Alexander Isak | Liverpool | FWD | 100 | 0.426 | 37 |
| Max Dowman | Max Dowman | Arsenal | MID | 100 | 0.405 | 37 |
| Noni Madueke | Noni Madueke | Arsenal | MID | 100 | 0.402 | 37 |
| Joshua Zirkzee | Joshua Zirkzee | Man Utd | FWD | 100 | 0.304 | 2 |
| Charalampos Kostoulas | Charalampos Kostoulas | Brighton | FWD | 100 | 0.301 | 2 |
| Edward Nketiah | Eddie Nketiah | Crystal Palace | FWD | 100 | 0.308 | 2 |
| Eberechi Eze | Eberechi Eze | Crystal Palace | MID | 100 | 0.352 | 2 |
| Taiwo Awoniyi | Taiwo Awoniyi | Nott'm Forest | FWD | 100 | 0.310 | 2 |
| Hamed Traore | Hamed Traorè | Bournemouth | MID | 100 | 0.308 | 2 |
| Kai Havertz | Kai Havertz | Arsenal | FWD | 100 | 0.429 | 2 |
| Reiss Nelson | Reiss Nelson | Arsenal | MID | 100 | 0.381 | 2 |
| Leandro Trossard | Leandro Trossard | Arsenal | MID | 100 | 0.306 | 1 |
| Christopher Nkunku | Christopher Nkunku | Chelsea | MID | 100 | 0.380 | 1 |
| Phil Foden | Phil Foden | Man City | MID | 100 | 0.349 | 1 |
| Taiwo Awoniyi | Taiwo Awoniyi | Nott'm Forest | FWD | 100 | 0.369 | 1 |
| Omar Marmoush | Omar Marmoush | Man City | MID | 100 | 0.463 | 38 |
| Florian Wirtz | Florian Wirtz | Liverpool | MID | 100 | 0.312 | 12 |
| Tyrique George | Tyrique George | Chelsea | MID | 100 | 0.327 | 12 |
| Charalampos Kostoulas | Charalampos Kostoulas | Brighton | FWD | 100 | 0.328 | 12 |
| Stefanos Tzimas | Stefanos Tzimas | Brighton | FWD | 100 | 0.354 | 12 |
| Justin Kluivert | Justin Kluivert | Bournemouth | MID | 100 | 0.323 | 12 |
| Antoine Semenyo | Antoine Semenyo | Bournemouth | MID | 100 | 0.438 | 12 |
| Andre Harriman-Annous | Andre Harriman-Annous | Arsenal | MID | 100 | 0.316 | 12 |
| Kai Havertz | Kai Havertz | Arsenal | FWD | 100 | 0.359 | 12 |
| Viktor Gyokeres | Viktor Gyökeres | Arsenal | FWD | 100 | 0.452 | 12 |
| Niclas Fullkrug | Niclas Füllkrug | West Ham | FWD | 100 | 0.377 | 11 |
| Arnaud Kalimuendo | Arnaud Kalimuendo | Nott'm Forest | FWD | 100 | 0.323 | 11 |
| Chris Wood | Chris Wood | Nott'm Forest | FWD | 100 | 0.347 | 11 |
| Alexander Isak | Alexander Isak | Liverpool | FWD | 100 | 0.362 | 11 |
| Tyrique George | Tyrique George | Chelsea | MID | 100 | 0.365 | 11 |
| William Osula | William Osula | Newcastle | FWD | 100 | 0.304 | 11 |
| Sean Neave | Sean Neave | Newcastle | FWD | 100 | 0.333 | 10 |
| Chris Wood | Chris Wood | Nott'm Forest | FWD | 100 | 0.316 | 10 |
| Joshua Zirkzee | Joshua Zirkzee | Man Utd | FWD | 100 | 0.304 | 10 |
| Alexander Isak | Alexander Isak | Liverpool | FWD | 100 | 0.492 | 10 |
| Jonah Kusi-Asare | Jonah Kusi-Asare | Fulham | FWD | 100 | 0.327 | 10 |
| Edward Nketiah | Eddie Nketiah | Crystal Palace | FWD | 100 | 0.352 | 10 |
| Max Dowman | Max Dowman | Arsenal | MID | 100 | 0.334 | 10 |
| Sean Neave | Sean Neave | Newcastle | FWD | 100 | 0.323 | 9 |
| Chidozie Obi | Chido Obi | Man Utd | FWD | 100 | 0.385 | 9 |
| Joel Piroe | Joël Piroe | Leeds | FWD | 100 | 0.367 | 9 |
| Alexander Isak | Alexander Isak | Liverpool | FWD | 100 | 0.463 | 9 |
| Ismaila Sarr | Ismaïla Sarr | Crystal Palace | MID | 100 | 0.340 | 14 |
| Kai Havertz | Kai Havertz | Arsenal | FWD | 100 | 0.364 | 14 |
| Leandro Trossard | Leandro Trossard | Arsenal | MID | 100 | 0.360 | 14 |
| Jayden Danns | Jayden Danns | Liverpool | FWD | 100 | 0.364 | 13 |
| Federico Chiesa | Federico Chiesa | Liverpool | MID | 100 | 0.305 | 13 |
| Mohamed Salah | Mohamed Salah | Liverpool | MID | 100 | 0.444 | 13 |
| Dane Scarlett | Dane Scarlett | Spurs | FWD | 100 | 0.301 | 13 |
| Taiwo Awoniyi | Taiwo Awoniyi | Nott'm Forest | FWD | 100 | 0.334 | 13 |
| Chris Wood | Chris Wood | Nott'm Forest | FWD | 100 | 0.334 | 13 |
| Oscar Bobb | Oscar Bobb | Man City | MID | 100 | 0.311 | 13 |
| William Osula | William Osula | Newcastle | FWD | 100 | 0.308 | 13 |
| Evann Guessand | Evann Guessand | Aston Villa | MID | 100 | 0.323 | 13 |
| Benjamin Sesko | Benjamin Sesko | Man Utd | FWD | 100 | 0.455 | 12 |
| Jayden Danns | Jayden Danns | Liverpool | FWD | 100 | 0.385 | 12 |
| Jayden Danns | Jayden Danns | Liverpool | FWD | 100 | 0.310 | 15 |
| Mohamed Salah | Mohamed Salah | Liverpool | MID | 100 | 0.418 | 15 |
| Taiwo Awoniyi | Taiwo Awoniyi | Nott'm Forest | FWD | 100 | 0.308 | 15 |
| Stefanos Tzimas | Stefanos Tzimas | Brighton | FWD | 100 | 0.420 | 15 |
| Arnaud Kalimuendo | Arnaud Kalimuendo | Nott'm Forest | FWD | 100 | 0.306 | 14 |
| Taiwo Awoniyi | Taiwo Awoniyi | Nott'm Forest | FWD | 100 | 0.364 | 14 |
| Chris Wood | Chris Wood | Nott'm Forest | FWD | 100 | 0.347 | 14 |
| Sean Neave | Sean Neave | Newcastle | FWD | 100 | 0.312 | 14 |
| William Osula | William Osula | Newcastle | FWD | 100 | 0.333 | 14 |
| Benjamin Sesko | Benjamin Sesko | Man Utd | FWD | 100 | 0.500 | 14 |
| Jayden Danns | Jayden Danns | Liverpool | FWD | 100 | 0.400 | 14 |
| Rio Ngumoha | Rio Ngumoha | Liverpool | MID | 100 | 0.322 | 14 |
| Omar Marmoush | Omar Marmoush | Man City | MID | 100 | 0.373 | 14 |
| Taiwo Awoniyi | Taiwo Awoniyi | Nott'm Forest | FWD | 100 | 0.331 | 16 |
| Jayden Danns | Jayden Danns | Liverpool | FWD | 100 | 0.364 | 16 |
| Tyrique George | Tyrique George | Chelsea | MID | 100 | 0.300 | 16 |
| Kevin Schade | Kevin Schade | Brentford | MID | 100 | 0.312 | 16 |
| Max Dowman | Max Dowman | Arsenal | MID | 100 | 0.365 | 16 |
| Andre Harriman-Annous | Andre Harriman-Annous | Arsenal | MID | 100 | 0.385 | 16 |
| Ethan Nwaneri | Ethan Nwaneri | Arsenal | MID | 100 | 0.328 | 16 |
| Noni Madueke | Noni Madueke | Arsenal | MID | 100 | 0.406 | 16 |
| Benjamin Sesko | Benjamin Sesko | Man Utd | FWD | 100 | 0.413 | 15 |
| William Osula | William Osula | Newcastle | FWD | 100 | 0.455 | 15 |
| Sean Neave | Sean Neave | Newcastle | FWD | 100 | 0.380 | 15 |
| Jacob Murphy | Jacob Murphy | Newcastle | MID | 100 | 0.333 | 15 |
| Harvey Barnes | Harvey Barnes | Newcastle | MID | 100 | 0.392 | 15 |
| Oscar Bobb | Oscar Bobb | Man City | MID | 100 | 0.301 | 15 |
| Jayden Danns | Jayden Danns | Liverpool | FWD | 100 | 0.445 | 18 |
| Rio Ngumoha | Rio Ngumoha | Liverpool | MID | 100 | 0.327 | 18 |
| Andre Harriman-Annous | Andre Harriman-Annous | Arsenal | MID | 100 | 0.335 | 18 |
| Noni Madueke | Noni Madueke | Arsenal | MID | 100 | 0.343 | 18 |
| Eberechi Eze | Eberechi Eze | Arsenal | MID | 100 | 0.360 | 18 |
| Jayden Danns | Jayden Danns | Liverpool | FWD | 100 | 0.328 | 17 |
| William Osula | William Osula | Newcastle | FWD | 100 | 0.328 | 17 |
| Oscar Bobb | Oscar Bobb | Man City | MID | 100 | 0.346 | 17 |
| Lukas Nmecha | Lukas Nmecha | Leeds | FWD | 100 | 0.351 | 17 |
| Chris Wood | Chris Wood | Nott'm Forest | FWD | 100 | 0.312 | 17 |
| Eberechi Eze | Eberechi Eze | Arsenal | MID | 100 | 0.312 | 17 |
| Stefanos Tzimas | Stefanos Tzimas | Brighton | FWD | 100 | 0.400 | 17 |
| Danny Welbeck | Danny Welbeck | Brighton | FWD | 100 | 0.425 | 17 |
| Bryan Mbeumo | Bryan Mbeumo | Man Utd | MID | 100 | 0.308 | 17 |
| William Osula | William Osula | Newcastle | FWD | 100 | 0.323 | 16 |
| Kai Havertz | Kai Havertz | Arsenal | FWD | 100 | 0.395 | 20 |
| Eberechi Eze | Eberechi Eze | Arsenal | MID | 100 | 0.342 | 20 |
| Niclas Fullkrug | Niclas Füllkrug | West Ham | FWD | 100 | 0.312 | 19 |
| Divine Mukasa | Divine Mukasa | Man City | MID | 100 | 0.345 | 19 |
| Mason Mount | Mason Mount | Man Utd | MID | 100 | 0.330 | 19 |
| Jayden Danns | Jayden Danns | Liverpool | FWD | 100 | 0.364 | 19 |
| Edward Nketiah | Eddie Nketiah | Crystal Palace | FWD | 100 | 0.320 | 19 |
| Tyrique George | Tyrique George | Chelsea | MID | 100 | 0.361 | 19 |
| Sean Neave | Sean Neave | Newcastle | FWD | 100 | 0.328 | 19 |
| William Osula | William Osula | Newcastle | FWD | 100 | 0.354 | 19 |
| Kai Havertz | Kai Havertz | Arsenal | FWD | 100 | 0.382 | 19 |
| Andre Harriman-Annous | Andre Harriman-Annous | Arsenal | MID | 100 | 0.320 | 19 |
| Eberechi Eze | Eberechi Eze | Arsenal | MID | 100 | 0.343 | 19 |
| Niclas Fullkrug | Niclas Füllkrug | West Ham | FWD | 100 | 0.315 | 18 |
| Sean Neave | Sean Neave | Newcastle | FWD | 100 | 0.313 | 21 |
| William Osula | William Osula | Newcastle | FWD | 100 | 0.328 | 21 |
| Divine Mukasa | Divine Mukasa | Man City | MID | 100 | 0.381 | 21 |
| Edward Nketiah | Eddie Nketiah | Crystal Palace | FWD | 100 | 0.308 | 21 |
| Chidozie Obi | Chido Obi | Man Utd | FWD | 100 | 0.365 | 21 |
| Dango Ouattara | Dango Ouattara | Brentford | MID | 100 | 0.312 | 21 |
| Kai Havertz | Kai Havertz | Arsenal | FWD | 100 | 0.368 | 21 |
| Sean Neave | Sean Neave | Newcastle | FWD | 100 | 0.313 | 20 |
| William Osula | William Osula | Newcastle | FWD | 100 | 0.335 | 20 |
| Divine Mukasa | Divine Mukasa | Man City | MID | 100 | 0.372 | 20 |
| Jayden Danns | Jayden Danns | Liverpool | FWD | 100 | 0.308 | 20 |
| Hugo Ekitike | Hugo Ekitiké | Liverpool | FWD | 100 | 0.460 | 20 |
| Andre Harriman-Annous | Andre Harriman-Annous | Arsenal | MID | 100 | 0.324 | 20 |
| Francisco Evanilson de Lima Barbosa | Francisco Evanilson de Lima Barbosa | Bournemouth | FWD | 100 | 0.389 | 9 |
| Max Dowman | Max Dowman | Arsenal | MID | 100 | 0.306 | 9 |
| Callum Wilson | Callum Wilson | West Ham | FWD | 100 | 0.313 | 8 |
| Arnaud Kalimuendo | Arnaud Kalimuendo | Nott'm Forest | FWD | 100 | 0.315 | 8 |
| Divine Mukasa | Divine Mukasa | Man City | MID | 100 | 0.314 | 8 |
| Omar Marmoush | Omar Marmoush | Man City | MID | 100 | 0.337 | 8 |
| Rio Ngumoha | Rio Ngumoha | Liverpool | MID | 100 | 0.309 | 8 |
| Joshua Zirkzee | Joshua Zirkzee | Man Utd | FWD | 100 | 0.359 | 7 |
| Randal Kolo Muani | Randal Kolo Muani | Spurs | FWD | 100 | 0.321 | 7 |
| Omar Marmoush | Omar Marmoush | Man City | MID | 100 | 0.309 | 7 |
| Divine Mukasa | Divine Mukasa | Man City | MID | 100 | 0.394 | 7 |
| Max Dowman | Max Dowman | Arsenal | MID | 100 | 0.320 | 7 |
| Randal Kolo Muani | Randal Kolo Muani | Spurs | FWD | 100 | 0.448 | 6 |
| Sean Neave | Sean Neave | Newcastle | FWD | 100 | 0.327 | 22 |
| Richarlison de Andrade | Richarlison de Andrade | Spurs | FWD | 100 | 0.435 | 22 |
| Dane Scarlett | Dane Scarlett | Spurs | FWD | 100 | 0.383 | 22 |
| Wilson Isidor | Wilson Isidor | Sunderland | FWD | 100 | 0.350 | 22 |
| Kai Havertz | Kai Havertz | Arsenal | FWD | 100 | 0.352 | 22 |
| Benjamin Sesko | Benjamin Sesko | Man Utd | FWD | 100 | 0.322 | 22 |
| Jayden Danns | Jayden Danns | Liverpool | FWD | 100 | 0.435 | 22 |
| Joel Piroe | Joël Piroe | Leeds | FWD | 100 | 0.323 | 22 |
| Tyrique George | Tyrique George | Chelsea | MID | 100 | 0.307 | 22 |
| Enes Unal | Enes Ünal | Bournemouth | FWD | 100 | 0.308 | 22 |
| Donyell Malen | Donyell Malen | Aston Villa | MID | 100 | 0.338 | 22 |
| Callum Wilson | Callum Wilson | West Ham | FWD | 100 | 0.315 | 21 |
| Arnaud Kalimuendo | Arnaud Kalimuendo | Nott'm Forest | FWD | 100 | 0.310 | 21 |
| Taiwo Awoniyi | Taiwo Awoniyi | Nott'm Forest | FWD | 100 | 0.337 | 21 |
| Bukayo Saka | Bukayo Saka | Arsenal | MID | 100 | 0.343 | 24 |
| Tyrique George | Tyrique George | Chelsea | MID | 100 | 0.362 | 24 |
| Ollie Watkins | Ollie Watkins | Aston Villa | FWD | 100 | 0.398 | 24 |
| Sean Neave | Sean Neave | Newcastle | FWD | 100 | 0.316 | 23 |
| William Osula | William Osula | Newcastle | FWD | 100 | 0.320 | 23 |
| Divine Mukasa | Divine Mukasa | Man City | MID | 100 | 0.388 | 23 |
| Cole Palmer | Cole Palmer | Chelsea | MID | 100 | 0.349 | 23 |
| Edward Nketiah | Eddie Nketiah | Crystal Palace | FWD | 100 | 0.311 | 23 |
| Randal Kolo Muani | Randal Kolo Muani | Spurs | FWD | 100 | 0.316 | 23 |
| Zian Flemming | Zian Flemming | Burnley | FWD | 100 | 0.312 | 23 |
| Jayden Danns | Jayden Danns | Liverpool | FWD | 100 | 0.347 | 23 |
| Kai Havertz | Kai Havertz | Arsenal | FWD | 100 | 0.372 | 23 |
| Bendito Mantato | Bendito Mantato | Man Utd | MID | 100 | 0.400 | 25 |
| Mason Mount | Mason Mount | Man Utd | MID | 100 | 0.305 | 25 |
| Jayden Danns | Jayden Danns | Liverpool | FWD | 100 | 0.308 | 25 |
| Joel Piroe | Joël Piroe | Leeds | FWD | 100 | 0.318 | 25 |
| Lukas Nmecha | Lukas Nmecha | Leeds | FWD | 100 | 0.394 | 25 |
| Edward Nketiah | Eddie Nketiah | Crystal Palace | FWD | 100 | 0.345 | 25 |
| Jean-Philippe Mateta | Jean-Philippe Mateta | Crystal Palace | FWD | 100 | 0.352 | 25 |
| Bukayo Saka | Bukayo Saka | Arsenal | MID | 100 | 0.373 | 25 |
| Edward Nketiah | Eddie Nketiah | Crystal Palace | FWD | 100 | 0.323 | 24 |
| Jean-Philippe Mateta | Jean-Philippe Mateta | Crystal Palace | FWD | 100 | 0.323 | 24 |
| Taiwo Awoniyi | Taiwo Awoniyi | Nott'm Forest | FWD | 100 | 0.362 | 24 |
| Bendito Mantato | Bendito Mantato | Man Utd | MID | 100 | 0.385 | 24 |
| Joshua Zirkzee | Joshua Zirkzee | Man Utd | FWD | 100 | 0.385 | 24 |
| Jayden Danns | Jayden Danns | Liverpool | FWD | 100 | 0.355 | 24 |
| Divine Mukasa | Divine Mukasa | Man City | MID | 100 | 0.451 | 6 |
| Hugo Ekitike | Hugo Ekitiké | Liverpool | FWD | 100 | 0.417 | 6 |
| Cole Palmer | Cole Palmer | Chelsea | MID | 100 | 0.423 | 6 |
| Federico Chiesa | Federico Chiesa | Liverpool | MID | 100 | 0.306 | 5 |
| Taiwo Awoniyi | Taiwo Awoniyi | Nott'm Forest | FWD | 100 | 0.365 | 5 |
| Stefanos Tzimas | Stefanos Tzimas | Brighton | FWD | 100 | 0.316 | 5 |
| Randal Kolo Muani | Randal Kolo Muani | Spurs | FWD | 100 | 0.319 | 5 |
| Randal Kolo Muani | Randal Kolo Muani | Spurs | FWD | 100 | 0.398 | 4 |
| Sean Neave | Sean Neave | Newcastle | FWD | 100 | 0.347 | 4 |
| Jacob Ramsey | Jacob Ramsey | Newcastle | MID | 100 | 0.347 | 4 |
| Jonah Kusi-Asare | Jonah Kusi-Asare | Fulham | FWD | 100 | 0.328 | 4 |
| Ismaila Sarr | Ismaïla Sarr | Crystal Palace | MID | 100 | 0.333 | 4 |
| Alexander Isak | Alexander Isak | Liverpool | FWD | 100 | 0.546 | 4 |
| Jayden Danns | Jayden Danns | Liverpool | FWD | 100 | 0.335 | 27 |
| Joshua Zirkzee | Joshua Zirkzee | Man Utd | FWD | 100 | 0.311 | 27 |
| Jean-Philippe Mateta | Jean-Philippe Mateta | Crystal Palace | FWD | 100 | 0.488 | 27 |
| Yoane Wissa | Yoane Wissa | Newcastle | FWD | 100 | 0.370 | 26 |
| Jayden Danns | Jayden Danns | Liverpool | FWD | 100 | 0.323 | 26 |
| Taiwo Awoniyi | Taiwo Awoniyi | Nott'm Forest | FWD | 100 | 0.389 | 26 |
| Jean-Philippe Mateta | Jean-Philippe Mateta | Crystal Palace | FWD | 100 | 0.509 | 26 |
| Dominic Calvert-Lewin | Dominic Calvert-Lewin | Leeds | FWD | 100 | 0.320 | 26 |
| Kai Havertz | Kai Havertz | Arsenal | FWD | 100 | 0.310 | 26 |
| Jean-Philippe Mateta | Jean-Philippe Mateta | Crystal Palace | FWD | 100 | 0.417 | 29 |
| Nick Woltemade | Nick Woltemade | Newcastle | FWD | 100 | 0.375 | 29 |
| Yoane Wissa | Yoane Wissa | Newcastle | FWD | 100 | 0.367 | 29 |
| Omar Marmoush | Omar Marmoush | Man City | MID | 100 | 0.454 | 29 |
| Jonah Kusi-Asare | Jonah Kusi-Asare | Fulham | FWD | 100 | 0.325 | 29 |
| Harry Wilson | Harry Wilson | Fulham | MID | 100 | 0.364 | 29 |
| Sean Neave | Sean Neave | Newcastle | FWD | 100 | 0.318 | 28 |
| Jean-Philippe Mateta | Jean-Philippe Mateta | Crystal Palace | FWD | 100 | 0.323 | 28 |
| Jayden Danns | Jayden Danns | Liverpool | FWD | 100 | 0.400 | 28 |
| Federico Chiesa | Federico Chiesa | Liverpool | MID | 100 | 0.334 | 28 |
| Phil Foden | Phil Foden | Man City | MID | 100 | 0.311 | 28 |
| Jonah Kusi-Asare | Jonah Kusi-Asare | Fulham | FWD | 100 | 0.316 | 28 |
| Charalampos Kostoulas | Charalampos Kostoulas | Brighton | FWD | 100 | 0.330 | 28 |
| Kai Havertz | Kai Havertz | Arsenal | FWD | 100 | 0.364 | 27 |
| Charalampos Kostoulas | Charalampos Kostoulas | Brighton | FWD | 100 | 0.409 | 32 |
| Andre Harriman-Annous | Andre Harriman-Annous | Arsenal | MID | 100 | 0.302 | 32 |
| Bukayo Saka | Bukayo Saka | Arsenal | MID | 100 | 0.354 | 32 |
| Sean Neave | Sean Neave | Newcastle | FWD | 100 | 0.309 | 31 |
| Joel Piroe | Joël Piroe | Leeds | FWD | 100 | 0.315 | 31 |
| Jonah Kusi-Asare | Jonah Kusi-Asare | Fulham | FWD | 100 | 0.345 | 31 |
| Mohamed Salah | Mohamed Salah | Liverpool | MID | 100 | 0.328 | 31 |
| Charalampos Kostoulas | Charalampos Kostoulas | Brighton | FWD | 100 | 0.323 | 31 |
| Charalampos Kostoulas | Charalampos Kostoulas | Brighton | FWD | 100 | 0.306 | 30 |
| Joshua Zirkzee | Joshua Zirkzee | Man Utd | FWD | 100 | 0.302 | 30 |
| Yoane Wissa | Yoane Wissa | Newcastle | FWD | 100 | 0.302 | 30 |
| Remy Rees-Dottin | Remy Rees-Dottin | Bournemouth | MID | 100 | 0.323 | 30 |
| Romelle Donovan | Romelle Donovan | Brentford | MID | 100 | 0.306 | 30 |
| Jayden Danns | Jayden Danns | Liverpool | FWD | 100 | 0.390 | 29 |
| Federico Chiesa | Federico Chiesa | Liverpool | MID | 100 | 0.336 | 34 |
| Leandro Trossard | Leandro Trossard | Arsenal | MID | 100 | 0.319 | 34 |
| Richarlison de Andrade | Richarlison de Andrade | Spurs | FWD | 100 | 0.358 | 33 |
| Taiwo Awoniyi | Taiwo Awoniyi | Nott'm Forest | FWD | 100 | 0.417 | 33 |
| Sean Neave | Sean Neave | Newcastle | FWD | 100 | 0.305 | 33 |
| Anthony Gordon | Anthony Gordon | Newcastle | MID | 100 | 0.350 | 33 |
| Yoane Wissa | Yoane Wissa | Newcastle | FWD | 100 | 0.401 | 33 |
| Omar Marmoush | Omar Marmoush | Man City | MID | 100 | 0.317 | 33 |
| Joao Pedro Junqueira de Jesus | João Pedro Junqueira de Jesus | Chelsea | FWD | 100 | 0.432 | 33 |
| Joshua Zirkzee | Joshua Zirkzee | Man Utd | FWD | 100 | 0.310 | 32 |
| Federico Chiesa | Federico Chiesa | Liverpool | MID | 100 | 0.313 | 32 |
| Hugo Ekitike | Hugo Ekitiké | Liverpool | FWD | 100 | 0.493 | 32 |
| Edward Nketiah | Eddie Nketiah | Crystal Palace | FWD | 100 | 0.323 | 32 |
| Omar Marmoush | Omar Marmoush | Man City | MID | 100 | 0.359 | 32 |
| Wilson Isidor | Wilson Isidor | Sunderland | FWD | 100 | 0.307 | 36 |
| Benjamin Sesko | Benjamin Sesko | Man Utd | FWD | 100 | 0.447 | 36 |
| Morgan Gibbs-White | Morgan Gibbs-White | Nott'm Forest | MID | 100 | 0.347 | 36 |
| Mohamed Salah | Mohamed Salah | Liverpool | MID | 100 | 0.385 | 36 |
| Nick Woltemade | Nick Woltemade | Newcastle | FWD | 100 | 0.403 | 35 |
| Anthony Gordon | Anthony Gordon | Newcastle | MID | 100 | 0.308 | 35 |
| Alexander Isak | Alexander Isak | Liverpool | FWD | 100 | 0.414 | 35 |
| Joel Piroe | Joël Piroe | Leeds | FWD | 100 | 0.462 | 35 |
| Remy Rees-Dottin | Remy Rees-Dottin | Bournemouth | MID | 100 | 0.316 | 35 |
| Kai Havertz | Kai Havertz | Arsenal | FWD | 100 | 0.395 | 35 |
| Norberto Bercique Gomes Betuncal | Norberto Bercique Gomes Betuncal | Everton | FWD | 100 | 0.314 | 34 |
| Liam Delap | Liam Delap | Chelsea | FWD | 100 | 0.392 | 4 |
| Charalampos Kostoulas | Charalampos Kostoulas | Brighton | FWD | 100 | 0.381 | 4 |
| Max Dowman | Max Dowman | Arsenal | MID | 100 | 0.303 | 4 |
| Yoane Wissa | Yoane Wissa | Brentford | FWD | 100 | 0.331 | 3 |
| Taiwo Awoniyi | Taiwo Awoniyi | Nott'm Forest | FWD | 100 | 0.417 | 3 |
| Chidozie Obi | Chido Obi | Man Utd | FWD | 100 | 0.420 | 3 |
| Joel Piroe | Joël Piroe | Leeds | FWD | 100 | 0.301 | 3 |
| Cole Palmer | Cole Palmer | Chelsea | MID | 100 | 0.434 | 3 |
| Cole Palmer | Cole Palmer | Chelsea | MID | 100 | 0.434 | 2 |
| Christopher Nkunku | Christopher Nkunku | Chelsea | MID | 100 | 0.417 | 2 |
| Sean Neave | Sean Neave | Newcastle | FWD | 100 | 0.303 | 2 |
| Chidozie Obi | Chido Obi | Man Utd | FWD | 100 | 0.320 | 2 |
| Charalampos Kostoulas | Charalampos Kostoulas | Brighton | FWD | 100 | 0.366 | 1 |
| Evann Guessand | Evann Guessand | Aston Villa | MID | 100 | 0.334 | 1 |
| Harvey Elliott | Harvey Elliott | Liverpool | MID | 100 | 0.320 | 1 |
| Rio Ngumoha | Rio Ngumoha | Liverpool | MID | 100 | 0.387 | 1 |

## Constraint carried forward to the de-vig step (from the spelling-variant finding)

Different books spell one player differently on the same board ("Josh King" / "Joshua King"; "Ibrahim Konate" / "Ibrahima Konaté"). After this crosswalk both strings map to the same element. **The consensus must merge by `element`, never by name string** — a string-keyed merge would count that player twice (once per spelling) and halve the weight of every other player on the board. The de-vig step must group prices by (event, element) and take the per-book mean before any cross-book consensus; the `books` column on every row records which books priced the string so the per-book grouping is checkable.

## Classification of every remaining null (nothing forced)

- **Not yet an FPL element at that gameweek:** academy players priced by books before FPL registered them (vaastav has no row at the priced gameweeks; the element's first row comes later). Correct nulls; verified per name in the build output.
- **Departed-player listings:** a book still lists a player at a club he has left (2025-26: Marc Guéhi at Palace GW23 while at Man City; Brennan Johnson at Spurs GW20–21 while at Palace; Jacob Ramsey at Villa GW3–5 while at Newcastle; Facundo Buonanotte at Chelsea GW22–23 while at Leeds). The club-at-gameweek pool refused them; correct nulls.
- **Not an FPL element in that season at all:** e.g. Thiago Silva (Chelsea board GW16 2024-25, left in 2024), and ~30 academy names with no FPL element.
- **Refused as uncertain:** 'Yeimar Mosquera' (15 boards, 2025-26) — the two Mosqueras are Yerson (Wolves) and Cristhian (Arsenal); 'Yeimar' is neither's name and the boards span both clubs' fixtures. No guess; null.
