# Prompt for Copilot: audit how the completion check closed each direction

Paste the text below to Copilot as is.

---

Both the rule run and the model run of the multi-site case ended with the
completion check passed, but the ground truth has locations covered by the
down cells, some with coverage holes, that neither run queried. I want to
know, for each such location, how the check came to close its direction.
Read the stored run directories and the ground truth; do not run anything,
do not change code, and do not attach raw files. Give me one report.

Do this for each of the two runs separately.

Step 1. From the ground truth, list every location that a down cell
covers and that the run never queried. For each, give its area id, its bin
(the 30 degree sector from the site; for the multi-site case say which
site's bins you use and why), its distance from that site, and whether the
ground truth marks it as a coverage hole.

Step 2. For each such bin, walk the step records in order and tell me, in
plain words, the history of that bin: at which round it was first tested,
what its farthest covered location was at each round it changed, which
areas the check named as open items for it, which queries answered them,
and at which round the bin was declared closed. Quote the exact check
record that closed it: the bin status, the areas it read, and the counts
it read for each area (inside unqueried, sampled beyond, covered beyond,
resolution), as they stood at that round.

Step 3. For each unqueried covered location, say which one of these
describes why the check never asked for it:

a) the location is in an area the check read as resolved by sample in
   that bin; say how many samples were in that bin and where they were
   relative to the location;
b) the location is in an area the check read as resolved by boundary in
   that bin; say the boundary distance, the count of clean samples beyond
   it in that bin, and whether the location is nearer or farther than the
   boundary;
c) the location is farther than the reach limit beyond the bin's farthest
   covered location, so its area was never named;
d) the location is in a bin the check never tested (not active, not a
   neighbour of an active bin, or unobserved and closed as no activity);
e) the location is not in any activity area the geometry knows;
f) the location is in a bin closed at the frame cap or by the legacy edge
   rule;
g) none of the above; describe what you see.

Step 4. Give the totals: how many unqueried covered locations fall under
each letter, for each run, and how many of those are coverage holes.

Step 5. For the multi-site part only: say whether the check tested bins
around each down site separately, or around one site only, and whether any
unqueried covered location lies between the sites where the bins of the
two sites overlap or where neither site's active bins reach.

Report values with the file and the step number they come from. If a
step record does not contain enough to answer a question, say which field
is missing rather than guessing.
