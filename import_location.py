import os

import django
import pandas as pd
from django.contrib.gis.geos import Point

from utils.ui import SpinnerFrame

os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "rosak.settings")
django.setup()

from jejak.models import Bus, Location  # noqa E402

INPUT_FILENAME = "./utils/2022-05_0.json"

DT_TARGET = "dt_received"

DTYPE = {
    "latitude": "Float64",
    "longitude": "Float64",
    "dir": "Float32",
    "speed": "Float32",
    "angle": "Float32",
    "captain_id": "Int32",
    "trip_rev_kind": "Int32",
    "engine_status": "Int32",
    "accessibility": "Int32",
    "busstop_id": "Int32",
}

COL_RENAME = {
    "bus_no": "bus",
    "trip_no": "trip",
    "trip_rev_kind": "triprev",
    "busstop_id": "busstop",
    "captain_id": "captain",
    "engine_status": "enginestatus",
}


print("⏩ Reading data...")
counter = 0
bus_dict = {}

spinner_frame = SpinnerFrame()

with pd.read_json(INPUT_FILENAME, lines=True, dtype=DTYPE, chunksize=100000) as reader:
    for chunk in reader:
        chunk = chunk.rename(columns=COL_RENAME)

        identifiers = set(chunk["bus"].dropna().unique())
        diff = identifiers.difference(set(bus_dict.keys()))

        if diff:
            print("⏩ Importing data for bus...")
            Bus.objects.bulk_create(
                [Bus(identifier=identifier) for identifier in diff],
                ignore_conflicts=True,
            )

            bus_dict.update(
                Bus.objects.filter(identifier__in=diff).in_bulk(field_name="identifier")
            )
        else:
            print("⏩ Bus data populated, skipping...")

        print("⏩ Creating data objects...")
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

            if len(location_datas) % 1000 == 0:
                print(spinner_frame.get_spinner_frame() + " ", end="\r")

        print()
        print("⏩ Inserting to db...")
        created = Location.objects.bulk_create(
            location_datas,
            batch_size=10000,
            ignore_conflicts=True,
        )

        counter += len(created)

        print(f"⏩ Done import {counter} rows...")
