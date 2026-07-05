import json

words = json.load(open("words.json"))
clips = json.load(open("detected_clips.json"))["clips"]

SENT_END = (".", "?", "!")
PAUSE = 0.6  # gap that counts as a natural break

# indices of words that END a sentence (punctuation or long pause after)
sent_ends = set()
for i, w in enumerate(words):
    if w["word"].rstrip('"').rstrip("'").endswith(SENT_END):
        sent_ends.add(i)
    elif i + 1 < len(words) and words[i+1]["start"] - w["end"] >= PAUSE:
        sent_ends.add(i)

def snap(start, end):
    # find word containing/after start
    si = next((i for i, w in enumerate(words) if w["end"] > start), 0)
    # walk back to just after previous sentence end -> clip starts on a fresh sentence
    while si > 0 and (si - 1) not in sent_ends:
        si -= 1
    # find word containing/before end
    ei = next((i for i in range(len(words)-1, -1, -1) if words[i]["start"] < end), len(words)-1)
    # walk forward to the next sentence end -> clip ends on a complete thought
    while ei < len(words) - 1 and ei not in sent_ends:
        ei += 1
    return round(words[si]["start"], 2), round(words[ei]["end"] + 0.15, 2), si, ei

snapped = []
for c in clips:
    ns, ne, si, ei = snap(c["start_seconds"], c["end_seconds"])
    dur = ne - ns
    preview_start = " ".join(w["word"] for w in words[si:si+8])
    preview_end = " ".join(w["word"] for w in words[max(si,ei-7):ei+1])
    print(f"{c['title'][:40]:40} {c['start_seconds']:>6.0f}-{c['end_seconds']:<6.0f} -> {ns:>7.2f}-{ne:<7.2f} ({dur:5.1f}s)")
    print(f"    opens: \"{preview_start}...\"")
    print(f"    ends:  \"...{preview_end}\"")
    snapped.append({**c, "start_seconds": ns, "end_seconds": ne})

json.dump({"clips": snapped, "total_clips": len(snapped)}, open("snapped_clips.json","w"), indent=2)
print(f"\n{len(snapped)} snapped clips saved to snapped_clips.json")
