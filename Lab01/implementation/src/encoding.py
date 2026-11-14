"""Canonical byte encoding dùng cho mọi dữ liệu được hash, ký hoặc gửi qua mạng.

Quy tắc: JSON UTF-8, khóa object sắp theo thứ tự từ điển, không khoảng trắng,
chỉ cho phép dict (khóa chuỗi), list, str, int, bool và None. Số thực bị cấm vì
cách in số thực không bảo đảm giống nhau giữa các nền tảng.
"""
import json


def _check(obj):
    if obj is None or isinstance(obj, (str, bool, int)):
        return
    if isinstance(obj, list):
        for item in obj:
            _check(item)
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            if not isinstance(key, str):
                raise TypeError("canonical encoding: khóa phải là chuỗi")
            _check(value)
        return
    raise TypeError(f"canonical encoding: kiểu không hỗ trợ {type(obj).__name__}")


def canonical(obj) -> bytes:
    """Trả về bytes duy nhất cho một nội dung logic."""
    _check(obj)
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def decode(raw: bytes):
    return json.loads(raw.decode("utf-8"))
