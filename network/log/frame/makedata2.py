import csv

CSV_PATH = "/home/n2sl/yeon/qos/network/log/frame/frame_records_pacing.csv"

count_iskey_1 = 0
total_rows = 0

with open(CSV_PATH, "r", encoding="utf-8") as f:
    reader = csv.reader(f)
    header = next(reader, None)  # skip header

    for row in reader:
        if len(row) < 2:
            continue

        total_rows += 1

        value = row[1].strip()   # 두번째 필드 = isKeyFrame
        if value == "1":
            count_iskey_1 += 1

print(f"total_rows = {total_rows}")
print(f"isKeyFrame == 1 count = {count_iskey_1}")