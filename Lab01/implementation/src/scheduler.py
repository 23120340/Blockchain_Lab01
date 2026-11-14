"""Event queue một luồng với thời gian mô phỏng (mili giây, số nguyên).

Thứ tự xử lý = (thời điểm, số thứ tự đăng ký). Số thứ tự phá thế hòa nên hai
sự kiện cùng thời điểm luôn chạy theo đúng thứ tự được lên lịch.
"""
import heapq

from .encoding import canonical


class Scheduler:
    def __init__(self):
        self.now = 0
        self._queue = []
        self._seq = 0

    def at(self, time, fn, *args):
        if time < self.now:
            raise ValueError("không được lên lịch về quá khứ")
        self._seq += 1
        heapq.heappush(self._queue, (time, self._seq, fn, args))

    def after(self, delay, fn, *args):
        self.at(self.now + delay, fn, *args)

    def run(self, until, stop=None):
        """Chạy tới khi hết sự kiện, quá `until`, hoặc `stop()` trả True."""
        while self._queue:
            if stop is not None and stop():
                return
            time, _, fn, args = self._queue[0]
            if time > until:
                return
            heapq.heappop(self._queue)
            self.now = time
            fn(*args)


class EventLog:
    """Log JSONL canonical. Không có wall-clock, PID hay đường dẫn."""

    def __init__(self):
        self.lines = []

    def emit(self, t, node, type_, height, **fields):
        record = {"t": t, "node": node, "type": type_, "height": height}
        for key, value in fields.items():
            if value is not None:
                record[key] = value
        self.lines.append(canonical(record))

    def to_bytes(self) -> bytes:
        return b"".join(line + b"\n" for line in self.lines)
