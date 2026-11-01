# Answer: corridor cache per location

Option 1. Keep every corridor within the half-width per location, as a
list of (corridor id, distance) sorted by distance; the nearest is the
first entry. Derive the area's crossing list from the union of those
lists plus the shared grid cells, exactly as check 7 computes it today.
Keep `nearest_corridor` as a separate field only if a reader needs it.
