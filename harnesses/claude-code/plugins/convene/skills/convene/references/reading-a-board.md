# Reading a board

`convene board NAME` prints every published post, whole, attributed by
seat id and by harness/model. The seats saw neither model names nor,
in a panel, each other.

**Read every post before forming a view.** The order is rotated by round
so no seat anchors the read; still, notice which post you read first
and discount the anchoring.

**Separate three things per finding:** the claim, the evidence the seat
gave for it (a file:line, a failure scenario, a command), and whether
you can verify it against the repository yourself. A finding you can
verify is yours to carry into the synthesis. A finding you cannot verify
stays attributed to the seat.

**Look for agreement and for its absence.** Two seats naming the same
defect independently is strong evidence; one seat naming it is a lead.
A seat that calls sound what another calls broken is the most useful
line on the board: read both arguments and decide, or say you cannot.

**Weigh the receipts.** `convene status NAME` shows, per seat, the
served model, the tool call count and every red flag. A post from a
seat that compacted, or that ran without isolation, is not discarded,
but it is weighed with that known.

**Notice what nobody said.** The `What I checked and found sound`
section of each post is what makes silence evidence. If no seat looked
at the part you worried about, the panel did not cover it.
