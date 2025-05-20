import csv
import os

def save_to_csv(data, username, platform):
    os.makedirs("output", exist_ok=True)
    filepath = f"output/{username}_{platform}.csv"

    with open(filepath, "w", newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["Field", "value"])
        for key, value in data.items():
            writer.writerow([key, value])
    print(f"csv saved to: {filepath}")