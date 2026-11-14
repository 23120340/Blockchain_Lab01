"""Đóng gói bài nộp Lab 01 đúng quy cách đề.

    python make_submission.py 23120001 23120002 ...     # một MSSV cho mỗi thành viên
    python make_submission.py --draft                   # bản nháp để thử quy trình

Tạo  submission/Lab01_<MSSV...>/  và  submission/Lab01_<MSSV...>.zip  chứa đúng:
    src/  tests/  logs/  config/  README.md  REPORT.pdf  requirements.txt
ZIP có một thư mục gốc duy nhất. Không đưa .venv, __pycache__, file tạm hay nguồn báo cáo.
"""
import os
import shutil
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
IMPL = os.path.join(HERE, "implementation")
OUT = os.path.join(HERE, "submission")
DIRS = ["src", "tests", "logs", "config"]
FILES = ["README.md", "REPORT.pdf", "requirements.txt"]
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".venv"}


def main():
    args = sys.argv[1:]
    draft = args == ["--draft"]
    if draft:
        name = "Lab01_BAN-NHAP-CHUA-CO-MSSV"
    else:
        if not args or not all(a.isdigit() for a in args):
            sys.exit("Cần danh sách MSSV (chỉ gồm chữ số), ví dụ: python make_submission.py 23120001 23120002")
        name = "Lab01_" + "_".join(args)
        with open(os.path.join(IMPL, "REPORT.tex"), encoding="utf-8") as fh:
            if "[MSSV 1]" in fh.read():
                sys.exit("REPORT.tex còn placeholder thông tin nhóm. Điền, biên dịch lại REPORT.pdf rồi chạy lại.")
    target = os.path.join(OUT, name)
    shutil.rmtree(target, ignore_errors=True)
    os.makedirs(target)
    for d in DIRS:
        shutil.copytree(os.path.join(IMPL, d), os.path.join(target, d),
                        ignore=shutil.ignore_patterns(*SKIP_DIRS, "*.pyc"))
    for f in FILES:
        shutil.copy2(os.path.join(IMPL, f), os.path.join(target, f))
    zip_path = target + ".zip"
    if os.path.exists(zip_path):
        os.remove(zip_path)
    count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root, dirs, files in os.walk(target):
            dirs.sort()
            for f in sorted(files):
                full = os.path.join(root, f)
                zf.write(full, os.path.join(name, os.path.relpath(full, target)).replace("\\", "/"))
                count += 1
    with zipfile.ZipFile(zip_path) as zf:
        tops = {n.split("/")[0] for n in zf.namelist()}
        second = sorted({n.split("/")[1] for n in zf.namelist()})
    assert tops == {name}, tops
    print(f"{'BẢN NHÁP' if draft else 'Bài nộp'}: {zip_path}")
    print(f"  {count} file, {os.path.getsize(zip_path) / 1e6:.1f} MB; thư mục gốc: {name}/")
    print(f"  nội dung: {', '.join(second)}")
    if draft:
        print("  Đây CHƯA phải bài nộp: tên còn thiếu MSSV và báo cáo còn placeholder thông tin nhóm.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    main()
