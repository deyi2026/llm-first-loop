#!/usr/bin/env bash
set -euo pipefail
D="$1"
mkdir -p "$D/docs/sub" "$D/deep/l1/l2" "$D/notes"
printf 'a\n' > "$D/docs/a.md"; printf 'b\n' > "$D/docs/b.md"; printf 'c\n' > "$D/docs/c.txt"
printf 'd\n' > "$D/docs/sub/d.md"; printf 'e\n' > "$D/docs/sub/e.pdf"; printf 'f\n' > "$D/docs/sub/f.md"
printf 'g\n' > "$D/deep/l1/l2/g.md"
printf 'n\n' > "$D/notes/notes.md"; printf 't\n' > "$D/notes/notes.txt"
(cd "$D" && find . -name '*.md' | sort | sed 's|^\./||' > .fixture-md-list)
