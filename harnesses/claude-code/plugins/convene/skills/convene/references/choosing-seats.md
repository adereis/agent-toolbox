# Choosing seats

A seat is persona × harness × model × tools. Choose each on purpose.
`convene personas` prints every persona id with what it reviews, and
`convene doctor --no-probes` prints the harnesses installed here; take
both from the commands rather than from memory.

**Persona.** `convene personas list` prints the catalog. The starter set
covers a skeptic (`quinn-t-shun`), an adversary (`ada-versary`), a
maintainer (`connie-tinuity`), a measurer (`emma-pirical`), a threat
modeler (`sec-urity`), a reader of the outside (`axel-cess`), an
architect (`archie-tecture`), a tester (`tess-tcase`), a domain expert
(`xavier-pert`, who takes the domain from the brief) and a performance
reviewer (`percy-formance`). A
project can add its own under `.convene/personas/`; a project persona
shadows a plugin one with the same id. Three seats with three
perspectives beat five seats with one.

**Harness and model.** Independence is the point. When you are Claude,
put at least one seat on Codex when it is installed, and prefer a model
that is not the one you are running on. Every seat's served model is
verified from the harness's own evidence and stamped on its receipt; a
mismatch fails the seat rather than passing quietly. Name a model by
its family unless the user asked for a version: `opus`, `fable`, `terra`,
`sol`, `gemini-pro`, `flash`. The engine resolves a family to the newest
version that harness lists, so a plan never goes stale when a model ships.
A version such as `opus-5.5` or `gpt-5.6-terra` pins the seat to it. A
name the catalog cannot place is refused, and the refusal lists the
families it has.

**A judge.** A fanout's judge sees only the lettered attempts. Put it on
a model family that made none of them where you can: a model tends to
rate its own family's writing higher, so a Claude judge may favor the
Claude attempt for its style rather than its substance. A persona that
distrusts claims (`quinn-t-shun`) suits the role. On any tier but
`enforced`, its receipt says `judging is advisory`.

**Tools.** `read` (the default) lets a seat read the repository and its
materials. `none` is for a seat that must answer from the brief alone;
it cannot take materials. `write` adds edit and shell tools, which a
panel does not need. `research` adds the web; use it only when a seat
must check a source, and expect the board to mark that seat.

**Isolation.** `strongest` (the default) picks `enforced` on Linux with
bubblewrap, else `private-home`. Set a seat to `none` only for a
deliberate test of the difference, and expect its receipt to say so.

**Cost.** Seats run one at a time by default. Put a cheap seat first
when the brief is new: a broken assignment is found by whichever seat
runs first, and that seat should be the one it costs least to throw
away.
