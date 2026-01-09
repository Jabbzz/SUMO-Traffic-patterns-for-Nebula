import os
import sys
import math
import csv
import json
import traci
from pathlib import Path


SUMO_BINARY = "sumo"  # or "sumo-gui" 
SUMO_CFG = "Test_dublin_map/osm.sumocfg"  

# RSU's
RSU_FILE = Path("Test_dublin_map/rsus.json")

with RSU_FILE.open() as f:
    RSUS = json.load(f)

# how many simulation seconds correspond to one FL round
ROUND_LENGTH = 10.0  # e.g. 10 seconds of SUMO = 1 Nebula round

OUTPUT_CSV = "rsu_connections.csv"


def distance(p, q):
    return math.hypot(p[0] - q[0], p[1] - q[1])


def run():
    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time", "round", "veh_id", "rsu_id", "veh_x", "veh_y", "dist"])

        while traci.simulation.getMinExpectedNumber() > 0:
            traci.simulationStep()
            t = traci.simulation.getTime()  # seconds
            round_id = int(t // ROUND_LENGTH)

            veh_ids = traci.vehicle.getIDList()

            for veh_id in veh_ids:
                x_v, y_v = traci.vehicle.getPosition(veh_id)
                for rsu_id, rsu in RSUS.items():
                    d = distance((x_v, y_v), (rsu["x"], rsu["y"]))
                    if d <= rsu["radius"]:
                        writer.writerow([t, round_id, veh_id, rsu_id, round(x_v, 2), round(y_v, 2), round(d, 2)])


if __name__ == "__main__":
    # build SUMO command
    sumo_cmd = [SUMO_BINARY, "-c", SUMO_CFG, "--seed", str(42),]

    traci.start(sumo_cmd)
    try:
        run()
    finally:
        traci.close()
