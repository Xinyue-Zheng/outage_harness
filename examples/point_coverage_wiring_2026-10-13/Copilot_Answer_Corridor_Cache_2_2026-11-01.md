# Answer: when the roadside block is filled

Option 1. Fill the block in validation, in the program step that first
needs it, before the selector runs. Section 1.3 is amended: "execute
step" reads "the first program step of the round that needs the block,
which is validation". The rest stands: the whole block in one pass,
once per (area, corridor), the selector a pure read that raises when
the block is absent, the step record naming the blocks filled and the
seconds. A block filled for an action that is then rejected is kept;
it is static geometry and the next request reuses it.

Do not defer exact validation to execution: a rejection must happen
before anything is executed or charged, as today.
