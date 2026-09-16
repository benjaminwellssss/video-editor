#!/bin/bash
set -e
PROJ="E:/video-editor-projects/valheimin-ep3-longplay-vod"
SHORTS="$PROJ/shorts"
WORDS="$PROJ/transcript/words.json"
RAW="E:/Streaming/Videos/VOD/2026-09-13 23-02-44.mp4"
HANDLE="$PROJ/graphics/handle.png"
VENV_PY="$HOME/.cache/video-editor/whisperx-venv/Scripts/python.exe"
SCRIPTS="C:/Users/Bem/Desktop/video-editor/scripts"
OUTDIR="E:/Streaming/Videos/CLIPS/09-13-2026_Valheim"

declare -A DURS=(
  [vietnam_wall]=28.5
  [cabelas_rhyme]=18.9
  [drinking_song]=44.6
  [peter_lois_sleep]=53.8
  [joker_bit]=23.9
  [bog_standard_cascade]=51.2
  [nra_hsa_deer]=18.6
)

for slug in vietnam_wall cabelas_rhyme drinking_song peter_lois_sleep joker_bit bog_standard_cascade nra_hsa_deer; do
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
