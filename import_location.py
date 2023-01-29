import argparse
import os
import time

import django
import pandas as pd
from django.contrib.gis.geos import Point
from django.db import transaction

from utils.constants import COL_RENAME, DTYPE
from utils.ui import SpinnerFrame

os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "rosak.settings")
django.setup()

from jejak.models import Bus, Location  # noqa E402

argParser = argparse.ArgumentParser()
argParser.add_argument("-f", "--file", help="Input filename.")

args = argParser.parse_args()
INPUT_FILENAME: str = args.file
# INPUT_FILENAME = "./@data/to_import/*.json"
# INPUT_FILENAME = "/mnt/c/Users/tungn/OldDrive/data/workplace/2022-05.json"
FILENAME = INPUT_FILENAME.split("/")[-1]

sleep_time = 5


print(f"{FILENAME} ⏩ Reading data...")
counter = 0
bus_dict = {}

spinner_frame = SpinnerFrame()

with transaction.atomic(), pd.read_json(
    INPUT_FILENAME, lines=True, dtype=DTYPE, chunksize=100000
) as reader:
    for chunk in reader:
        chunk = chunk.rename(columns=COL_RENAME)

        identifiers = set(chunk["bus"].dropna().unique())
        diff = identifiers.difference(set(bus_dict.keys()))

        if diff:
            while True:
                try:
                    print(f"{FILENAME} 🚌 Importing data for bus...")

                    Bus.objects.bulk_create(
                        [Bus(identifier=identifier) for identifier in diff],
                        ignore_conflicts=True,
                    )
                    sleep_time = 5

                except Exception as e:
                    print(e)
                    print(f"{FILENAME} ❗ Error, retrying in {sleep_time} seconds...")
                    time.sleep(sleep_time)
                    sleep_time += 5

                    continue

                break

            bus_dict.update(
                Bus.objects.filter(identifier__in=diff).in_bulk(field_name="identifier")
            )
        else:
            print(f"{FILENAME} 📜 Bus data populated, skipping...")

        print(f"{FILENAME} 💫 Creating data objects...")
        location_datas = []
        for i, row in chunk.iterrows():
            location_datas.append(
                Location(
                    dt_received=row["dt_received"],
                    dt_gps=row["dt_gps"],
                    location=Point(
                        x=row["longitude"],
                        y=row["latitude"],
                    ),
                    dir=row["dir"] if str(row["dir"]) != "<NA>" else None,
                    speed=row["speed"] if str(row["speed"]) != "<NA>" else None,
                    angle=row["angle"] if str(row["angle"]) != "<NA>" else None,
                    bus_id=bus_dict[row["bus"]].id,
                )
            )

        while True:
            try:
                print(f"{FILENAME} ⏩ Inserting to db...")
                Location.objects.bulk_create(
                    location_datas,
                    batch_size=10000,
                    ignore_conflicts=True,
                )
                sleep_time = 5

            except Exception as e:
                print(e)
                print(f"{FILENAME} ❗ Error, retrying in {sleep_time} seconds...")
                time.sleep(sleep_time)
                sleep_time += 5

                continue

            break

        counter += len(location_datas)

        print(f"{FILENAME} ✅ Done import {counter} rows...")
