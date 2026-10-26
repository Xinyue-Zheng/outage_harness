# Prompt 2: separate, readable pictures

Follows `PROMPT.md`. The first result came back as one combined page in
black and white with overlapping text. Paste the text below as it is.

---

Redo the area impact figures. Keep the data and the point rule; change only the output.

1. One picture per file, never a combined page. Files per case and condition:
   signal_truth.png, signal_agent.png, capacity_truth_<HH00>.png and capacity_agent_<HH00>.png for every outage hour, and one per area: area_<id>.png. No "agent minus truth" picture.

2. Maps (signal_*, capacity_*): white background, figure 8×8 in, dpi 150, the 30 km window with the site as a black cross. Each area gets its own fixed colour from a categorical palette (blue, orange, aqua, yellow, magenta, green, violet, red; more than 8 areas: group the smallest as "other", grey), used for its outline (linewidth 1.5) and nowhere else. Points as dots, ms 5, coloured by their state, not by a ramp:
   green = fewer than half of the backups degraded (or congested), orange = at least half, red = all of them, black = no backup reaches the point, light grey small = sampled but no outage coverage, hollow grey = no sample.
   No text on the map itself. Put the numbers in a legend box to the right of the map: one line per area in the area's colour: "<id> <name>: <n> pts · no backup <%> · ≥ half <%> · all <%>". Title on top: "<site> · <truth|agent> · signal" or "... · capacity at <HH:00>". If the legend box would hold more than 12 lines, write it to the same file name with .txt instead and keep only the title on the picture.

3. Per-area pictures (area_<id>.png), one per area, 8×5 in: title "<id> <name> (<kind>) · truth <n> sampled · agent <n> sampled"; left: three paired horizontal bars (signal ≥ half, congested ≥ half at the worst truth hour, no backup), truth in blue, agent in green, value printed at the bar end, "not queried" when a side is absent; middle: two stacked class-mix bars (truth, agent) with the six classes in six distinct colours and a legend; right: the congested-≥-half share over the outage hours, truth blue, agent green, worst hour marked. The text for the area goes in area_<id>.txt next to it, in exactly the form of sample/area_S02.txt (synthetic numbers): header line, counts line, the truth paragraph, the agent paragraph with the differences, then the capacity-by-hour table truth / agent with the worst truth hour marked.

4. Use explicit colours everywhere (facecolor white, text black, grid light grey); never the default style, never grayscale. Font size 9 for labels, 11 for titles. Check every picture opens readable at 100 % before you finish; if any text overlaps, move it to the .txt file.
