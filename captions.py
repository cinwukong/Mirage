"""
The subtitles under the corner hologram, as plain logic (hologram.py draws them).

A reply is split into the same pieces Mirage speaks one at a time (speech.split_sentences), wrapped to the box width,
and shown a piece at a time in a box a few rows tall that scrolls up smoothly:
- following the voice: a piece appears when Mirage starts saying it (spoken()),
- or at speaking pace when the voice can't say where it is (the Windows voice, VoiceStudio: started()),
- or at reading pace when replies are subtitles only.
The piece being said is bright, the one before it faded. Nothing is ever cut off: a piece longer than the box scrolls
through while it's said.
"""

ROWS = 3
LINGER = 1.5          # seconds the last piece stays after it has been said or read
WAIT_FOR_VOICE = 6.0  # following the voice but it never started: carry on at speaking pace


def _split_default(text):
    from speech import split_sentences
    return split_sentences(text)


def wrap(text, measure, width):
    """Lines of text that each fit in width (pixels, as measure() counts them). A word too long for a line gets
    a line of its own and is broken where it has to be."""
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}" if cur else word
        if measure(trial) <= width:
            cur = trial
            continue
        if cur:
            lines.append(cur)
        while measure(word) > width and len(word) > 1:
            cut = len(word) - 1
            while cut > 1 and measure(word[:cut]) > width:
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        cur = word
    if cur:
        lines.append(cur)
    return lines


def reading_time(piece):
    return 1.2 + 0.05 * len(piece)


def speaking_time(piece, wpm):
    return len(piece.split()) * 60.0 / max(60.0, wpm) + 0.35


class Captions:
    def __init__(self, measure, width, rows=ROWS, split=None):
        self.measure, self.width, self.rows = measure, width, rows
        self.split = split or _split_default
        self.text = ""
        self.pieces, self.layout = [], []   # layout: [(piece index, line text)]
        self.current = 0
        self.offset = 0.0                   # rows scrolled (eases towards the target)
        self.done_at = 0.0
        self._times = None                  # start time of each piece when it runs on a clock
        self._durations = []
        self._started_at = 0.0              # when the current piece started (following the voice)
        self._voice = False                 # the voice has said where it is
        self._wait_until = 0.0
        self._dirty = False

    # ---- what to show ----
    def show(self, text, who="mirage", follow_voice=False, wpm=165, now=0.0):
        """A new reply (or "you" line). follow_voice: Mirage is about to say it, so wait for spoken() or started();
        otherwise it runs at reading pace."""
        self.text = text
        self.pieces = [f"You: {text}"] if who == "you" else (self.split(text) or [text])
        self.layout = [(i, line) for i, piece in enumerate(self.pieces) for line in wrap(piece, self.measure, self.width)]
        self.current, self.offset, self._voice = 0, 0.0, False
        follow_voice = follow_voice and who != "you"
        self._durations = [speaking_time(p, wpm) if follow_voice else reading_time(p) for p in self.pieces]
        if follow_voice:
            self._times, self._started_at, self._wait_until = None, now, now + WAIT_FOR_VOICE
            self.done_at = self._wait_until + sum(self._durations) + LINGER
        else:
            self._run_clock(now)
        self._dirty = True

    def spoken(self, text, index, now=0.0):
        """The voice has started saying piece `index` of `text` (news about another reply is ignored)."""
        if text != self.text or not 0 <= index < len(self.pieces):
            return
        self._times, self._voice = None, True
        if index > self.current:
            self.current, self._dirty = index, True
        self._started_at = now
        self.done_at = now + sum(self._durations[index:]) + LINGER

    def started(self, text, now=0.0):
        """The voice has started saying all of `text` at once and won't say where it is: go at speaking pace."""
        if text == self.text and not self._voice:
            self._run_clock(now)

    def _run_clock(self, now):
        times, t = [], now
        for d in self._durations:
            times.append(t)
            t += d
        self._times = times
        self.done_at = t + LINGER

    def clear(self):
        self.text, self.pieces, self.layout, self.done_at, self._dirty = "", [], [], 0.0, True

    # ---- time passing ----
    def tick(self, now) -> bool:
        """Move on to the piece due now and ease the scroll. True if what's drawn changed."""
        if not self.pieces:
            return False
        if self._times is None and not self._voice and now >= self._wait_until:
            self._run_clock(now)  # the voice never started: carry on at speaking pace
        if self._times is not None:
            due = max([i for i, t in enumerate(self._times) if t <= now] or [0])
            if due != self.current:
                self.current, self._dirty = due, True
        target = self._target(now)
        if abs(target - self.offset) > 0.01:
            self.offset += (target - self.offset) * 0.3
            if abs(target - self.offset) < 0.02:
                self.offset = target
            self._dirty = True
        changed, self._dirty = self._dirty, False
        return changed

    def _target(self, now):
        rows = [k for k, (i, _) in enumerate(self.layout) if i == self.current]
        first, last = rows[0], rows[-1] + 1
        if last - first <= self.rows:  # the piece fits: it sits at the bottom, the one before above it
            return float(max(0, last - self.rows))
        start = self._times[self.current] if self._times else self._started_at
        done = min(1.0, max(0.0, (now - start) / max(0.5, self._durations[self.current])))
        return float(first + round(done * (last - first - self.rows)))  # longer than the box: scroll through it

    # ---- drawing ----
    def lines(self):
        """[(row from the top of the box, may be fractional while scrolling; text; brightness 0-1)] for lines of
        pieces that have started. Rows outside 0..rows-1 are off the box (the drawing clips them)."""
        out = []
        for k, (i, line) in enumerate(self.layout):
            if i > self.current:
                break
            pos = k - self.offset
            if -1 < pos < self.rows + 1:
                out.append((pos, line, 1.0 if i == self.current else 0.5 if i == self.current - 1 else 0.3))
        return out
