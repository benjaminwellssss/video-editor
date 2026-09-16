#!/bin/bash
set -e
PROJ="E:/video-editor-projects/valheimin-ep4-longplay-vod"
SHORTS="$PROJ/shorts"
WORDS="$PROJ/transcript/words.json"
RAW="E:/Streaming/Videos/VOD/2026-09-14 20-23-43-track0.mp4"
HANDLE="$PROJ/graphics/handle.png"
VENV_PY="$HOME/.cache/video-editor/whisperx-venv/Scripts/python.exe"
SCRIPTS="C:/Users/Bem/Desktop/video-editor/scripts"
OUTDIR="E:/Streaming/Videos/CLIPS/09-14-2026_Valheim"
mkdir -p "$OUTDIR"

if [ ! -f "$HANDLE" ]; then
  echo "-- rendering handle asset (first EP4 short) --"
  mkdir -p "$PROJ/graphics"
  "$VENV_PY" "$SCRIPTS/render_handle.py" "@beanjahmean" "$HANDLE"
fi

declare -A DURS=(
  [joe_rogan_penis]=35.31
  [naked_afraid]=59.33
  [guacacado]=46.90
  [unpaid_interns]=50.64
  [rage_tilt]=85.29
  [epic_baby_cry]=23.14
  [sweet_caroline]=22.46
  [crass_chris]=52.99
  [victory_items]=23.83
  [chamber_jammers]=23.71
  [ride_wife]=29.50
)

for slug in joe_rogan_penis naked_afraid guacacado unpaid_interns rage_tilt epic_baby_cry sweet_caroline crass_chris victory_items chamber_jammers ride_wife; do
  echo "=== $slug ==="
  seg="$SHORTS/${slug}_segments.json"
  base="$SHORTS/${slug}_base.mp4"
  cards="$SHORTS/${slug}_cards.json"
  capmov="$SHORTS/${slug}_captions.mov"
  final="$OUTDIR/short_${slug}.mp4"

  echo "-- compositing base --"
  python3 "$SCRIPTS/build_jumpcut_short.py" "$seg" "$RAW" "$base"

  echo "-- building caption cards --"
  "$VENV_PY" "$SCRIPTS/build_short_cards_from_segments.py" "$seg" "$WORDS" "$cards"

  if [ "$slug" == "ride_wife" ]; then
    echo "-- applying BRIDE -> RIDE correction --"
    python3 -c "
import json
with open('$cards', encoding='utf-8') as f:
    cards = json.load(f)
for c in cards:
    c['lines'] = [l.replace('BRIDE', 'RIDE') for l in c['lines']]
    for w in c.get('words', []):
        if w['text'] == 'BRIDE':
            w['text'] = 'RIDE'
with open('$cards', 'w', encoding='utf-8') as f:
    json.dump(cards, f, indent=2)
print('substitution applied')
"
  fi

  dur="${DURS[$slug]}"
  echo "-- rendering caption overlay ($dur s) --"
  "$VENV_PY" "$SCRIPTS/render_captions.py" "$cards" "$dur" "$capmov"

  echo "-- final composite --"
  ffmpeg -y -i "$base" -i "$capmov" -i "$HANDLE" \
    -filter_complex "[0:v][1:v]overlay=0:0[tmp];[tmp][2:v]overlay=0:0[outv]" \
    -map "[outv]" -map 0:a -c:v libx264 -preset fast -crf 18 -c:a aac -b:a 192k \
    "$final" -loglevel error

  dur_check=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$final")
  echo "-- done: $final (duration ${dur_check}s) --"
done

echo "ALL DONE"
