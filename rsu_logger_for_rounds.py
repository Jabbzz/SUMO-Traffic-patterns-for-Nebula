import math
import csv
import json
import traci
from pathlib import Path
from typing import Dict, Tuple, Optional, Set, Any


SUMO_BINARY = "sumo"  # or "sumo-gui"
SUMO_CFG = "Test_dublin_map/osm.sumocfg"

RSU_FILE = Path("Test_dublin_map/rsus.json")
ROUND_LENGTH = 10.0

MEMBERSHIP_JSONL = "round_membership.jsonl" # for each round, which vehicles were connected to which RSUs
RSU_STATS_CSV = "rsu_round_stats.csv" 
ROUND_SUMMARY_CSV = "round_summary.csv"


def load_and_validate_rsus(path: Path) -> Dict[str, Dict[str, float]]:
    with path.open() as f:
        rsus = json.load(f)

    if not isinstance(rsus, dict) or not rsus:
        raise ValueError("RSU file must be a non-empty JSON object: {rsu_id: {x,y,radius}}")

    for rsu_id, cfg in rsus.items():
        if not isinstance(cfg, dict):
            raise ValueError(f"{rsu_id} must map to an object with x/y/radius")
        for k in ("x", "y", "radius"):
            if k not in cfg:
                raise ValueError(f"{rsu_id} missing key '{k}'")
            if not isinstance(cfg[k], (int, float)):
                raise ValueError(f"{rsu_id}.{k} must be numeric, got {type(cfg[k]).__name__}")
        if cfg["radius"] <= 0:
            raise ValueError(f"{rsu_id}.radius must be > 0 (got {cfg['radius']})")

    return rsus


RSUS: Dict[str, Dict[str, float]] = load_and_validate_rsus(RSU_FILE)

# Euclidean Distance
def distance(p: Tuple[float, float], q: Tuple[float, float]) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])

# Closest RSU within radius. Makes sure that a vehicle only connnects to one RSU at a time.
def pick_closest_rsu(x_v: float, y_v: float) -> Tuple[Optional[str], Optional[float]]:
    best_rsu = None
    best_d = None
    for rsu_id, rsu in RSUS.items():
        d = distance((x_v, y_v), (rsu["x"], rsu["y"]))
        if d <= rsu["radius"]:
            if best_d is None or d < best_d:
                best_d = d
                best_rsu = rsu_id
    return best_rsu, best_d


def run():
    # Prepares output files for writing
    membership_f = open(MEMBERSHIP_JSONL, "w", encoding="utf-8")
    rsu_stats_f = open(RSU_STATS_CSV, "w", newline="", encoding="utf-8")
    round_summary_f = open(ROUND_SUMMARY_CSV, "w", newline="", encoding="utf-8")

    rsu_writer = csv.writer(rsu_stats_f)
    rsu_writer.writerow([
        "round", "t_start", "t_end",
        "rsu_id",
        "unique_vehicles",
        "total_connected_time_s",
        "avg_dist", "min_dist", "max_dist",
        "handover_in", "handover_out"
    ])

    round_writer = csv.writer(round_summary_f)
    round_writer.writerow([
        "round", "t_start", "t_end",
        "unique_vehicles_seen",
        "unique_connected_vehicles",
        "uncovered_vehicle_time_s"
    ])

    current_round: Optional[int] = None
    prev_t: Optional[float] = None

    # For this round, in this RSU, what vehicles were connected at least once. I might play with this later.
    round_membership: Dict[str, Set[str]] = {rsu_id: set() for rsu_id in RSUS.keys()}
    # total connection time per RSU. 
    rsu_conn_time: Dict[str, float] = {rsu_id: 0.0 for rsu_id in RSUS.keys()}
    # Average distance acumulated per RSU
    rsu_dist_sum: Dict[str, float] = {rsu_id: 0.0 for rsu_id in RSUS.keys()}
    rsu_dist_count: Dict[str, int] = {rsu_id: 0 for rsu_id in RSUS.keys()}
    rsu_dist_min: Dict[str, float] = {rsu_id: float("inf") for rsu_id in RSUS.keys()}
    rsu_dist_max: Dict[str, float] = {rsu_id: 0.0 for rsu_id in RSUS.keys()}
    rsu_handover_in: Dict[str, int] = {rsu_id: 0 for rsu_id in RSUS.keys()}
    rsu_handover_out: Dict[str, int] = {rsu_id: 0 for rsu_id in RSUS.keys()}

    round_unique_seen: Set[str] = set() # Vehicles that exist in this round
    round_unique_connected: Set[str] = set() # Vehicles that connected at some point in the round.
    # TODO
    round_uncovered_vehicle_time: float = 0.0 # Total time where vehicles were not covered by an RSU.

    # I want to detect handovers, so this should remember previous RSU assignments. I.e, veh_id -> last rsu_id
    prev_assignment: Dict[str, Optional[str]] = {}

    def reset_round_accumulators():
        nonlocal round_membership, rsu_conn_time, rsu_dist_sum, rsu_dist_count, rsu_dist_min, rsu_dist_max
        nonlocal rsu_handover_in, rsu_handover_out
        nonlocal round_unique_seen, round_unique_connected, round_uncovered_vehicle_time

        round_membership = {rsu_id: set() for rsu_id in RSUS.keys()}
        rsu_conn_time = {rsu_id: 0.0 for rsu_id in RSUS.keys()}
        rsu_dist_sum = {rsu_id: 0.0 for rsu_id in RSUS.keys()}
        rsu_dist_count = {rsu_id: 0 for rsu_id in RSUS.keys()}
        rsu_dist_min = {rsu_id: float("inf") for rsu_id in RSUS.keys()}
        rsu_dist_max = {rsu_id: 0.0 for rsu_id in RSUS.keys()}
        rsu_handover_in = {rsu_id: 0 for rsu_id in RSUS.keys()}
        rsu_handover_out = {rsu_id: 0 for rsu_id in RSUS.keys()}

        round_unique_seen = set()
        round_unique_connected = set()
        round_uncovered_vehicle_time = 0.0

    # at round r, this function will write the stats to files
    def flush_round(r: int):
        t_start = r * ROUND_LENGTH
        t_end = (r + 1) * ROUND_LENGTH

        membership_payload: Dict[str, Any] = {
            "round": r,
            "t_start": t_start,
            "t_end": t_end,
            "rsus": {rsu_id: sorted(list(veh_set)) for rsu_id, veh_set in round_membership.items()}
        }
        membership_f.write(json.dumps(membership_payload) + "\n")

        for rsu_id in RSUS.keys():
            uniq = len(round_membership[rsu_id])
            if rsu_dist_count[rsu_id] > 0:
                avg_dist = rsu_dist_sum[rsu_id] / rsu_dist_count[rsu_id]
                min_dist = rsu_dist_min[rsu_id]
                max_dist = rsu_dist_max[rsu_id]
            else:
                avg_dist = ""
                min_dist = ""
                max_dist = ""

            rsu_writer.writerow([
                r, t_start, t_end,
                rsu_id,
                uniq,
                round(rsu_conn_time[rsu_id], 3),
                avg_dist if avg_dist == "" else round(avg_dist, 3),
                min_dist if min_dist == "" else round(min_dist, 3),
                max_dist if max_dist == "" else round(max_dist, 3),
                rsu_handover_in[rsu_id],
                rsu_handover_out[rsu_id]
            ])

        round_writer.writerow([
            r, t_start, t_end,
            len(round_unique_seen),
            len(round_unique_connected),
            round(round_uncovered_vehicle_time, 3)
        ])

    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()
        t = traci.simulation.getTime()
        # ensures connected time is correct
        dt = 0.0 if prev_t is None else max(0.0, t - prev_t)
        prev_t = t

        # Determine current round
        r = int(t // ROUND_LENGTH)
        if current_round is None:
            current_round = r
            reset_round_accumulators()
        elif r != current_round:
            flush_round(current_round)
            current_round = r
            reset_round_accumulators()

        veh_ids = traci.vehicle.getIDList()

        for veh_id in veh_ids:
            round_unique_seen.add(veh_id)

            # Vehicle chooses closest RSU if it can
            x_v, y_v = traci.vehicle.getPosition(veh_id)
            rsu_id, d = pick_closest_rsu(x_v, y_v)

            prev_rsu = prev_assignment.get(veh_id, None)

            # Handover detection TODO
            if prev_rsu is not None and rsu_id is not None and prev_rsu != rsu_id:
                rsu_handover_out[prev_rsu] += 1
                rsu_handover_in[rsu_id] += 1

            prev_assignment[veh_id] = rsu_id

            # if no RSU, skip the rest
            if rsu_id is None:
                round_uncovered_vehicle_time += dt
                continue

            round_membership[rsu_id].add(veh_id)
            round_unique_connected.add(veh_id)

            rsu_conn_time[rsu_id] += dt

            if d is not None:
                rsu_dist_sum[rsu_id] += d
                rsu_dist_count[rsu_id] += 1
                rsu_dist_min[rsu_id] = min(rsu_dist_min[rsu_id], d)
                rsu_dist_max[rsu_id] = max(rsu_dist_max[rsu_id], d)

    if current_round is not None:
        flush_round(current_round)

    membership_f.close()
    rsu_stats_f.close()
    round_summary_f.close()


if __name__ == "__main__":
    sumo_cmd = [SUMO_BINARY, "-c", SUMO_CFG, "--seed", "42"]
    traci.start(sumo_cmd)
    try:
        run()
    finally:
        traci.close()
