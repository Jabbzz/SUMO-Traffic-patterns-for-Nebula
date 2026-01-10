import math
import json
import traci
from pathlib import Path
from typing import Dict, Tuple, Optional, Set, Any


SUMO_BINARY = "sumo"
SUMO_CFG = "Test_dublin_map/osm.sumocfg"

RSU_FILE = Path("Test_dublin_map/rsus.json")
ROUND_LENGTH = 10.0

OUT_MEMBERSHIP_JSONL = "round_membership.jsonl"
OUT_STATS_JSONL = "round_stats.jsonl"


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


RSUS = load_and_validate_rsus(RSU_FILE)


def distance(p: Tuple[float, float], q: Tuple[float, float]) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


def pick_closest_rsu(x_v: float, y_v: float) -> Optional[str]:
    """Closest RSU within radius for THIS step. None if uncovered."""
    best_rsu = None
    best_d = None
    for rsu_id, rsu in RSUS.items():
        d = distance((x_v, y_v), (rsu["x"], rsu["y"]))
        if d <= rsu["radius"]:
            if best_d is None or d < best_d:
                best_d = d
                best_rsu = rsu_id
    return best_rsu


def run():
    f_membership = open(OUT_MEMBERSHIP_JSONL, "w", encoding="utf-8")
    f_stats = open(OUT_STATS_JSONL, "w", encoding="utf-8")

    current_round: Optional[int] = None
    prev_t: Optional[float] = None

    # Per-round accumulators
    round_unique_seen: Set[str] = set()
    round_uncovered_vehicle_time: float = 0.0  # vehicle-seconds uncovered in this round

    # veh_rsu_time[veh_id][rsu_id] = seconds connected to rsu_id (within THIS round)
    veh_rsu_time: Dict[str, Dict[str, float]] = {}

    def reset_round():
        nonlocal round_unique_seen, round_uncovered_vehicle_time, veh_rsu_time
        round_unique_seen = set()
        round_uncovered_vehicle_time = 0.0
        veh_rsu_time = {}

    def flush_round(r: int):
        """
        Option 2: assign each vehicle to ONE RSU for the round
        = RSU with the most connected time within the round.
        """
        t_start = r * ROUND_LENGTH
        t_end = (r + 1) * ROUND_LENGTH

        # veh -> rsu assignment for this round
        assignment: Dict[str, Optional[str]] = {veh_id: None for veh_id in round_unique_seen}

        for veh_id, per_rsu in veh_rsu_time.items():
            best_rsu = None
            best_time = -1.0
            # deterministic tie-break by rsu_id (stable output)
            for rsu_id in sorted(per_rsu.keys()):
                t_conn = per_rsu[rsu_id]
                if t_conn > best_time:
                    best_time = t_conn
                    best_rsu = rsu_id
            assignment[veh_id] = best_rsu

        # membership rsu -> vehicles (1 RSU per vehicle)
        rsu_membership: Dict[str, Set[str]] = {rsu_id: set() for rsu_id in RSUS.keys()}
        connected_vehicles: Set[str] = set()

        for veh_id, rsu_id in assignment.items():
            if rsu_id is not None:
                rsu_membership[rsu_id].add(veh_id)
                connected_vehicles.add(veh_id)

        # High-value stat: total connected time per RSU (for assigned vehicles)
        rsu_total_connected_time: Dict[str, float] = {rsu_id: 0.0 for rsu_id in RSUS.keys()}
        for rsu_id, vehs in rsu_membership.items():
            total = 0.0
            for veh_id in vehs:
                total += veh_rsu_time.get(veh_id, {}).get(rsu_id, 0.0)
            rsu_total_connected_time[rsu_id] = round(total, 3)

        # 1) clean schedule file (Nebula input)
        membership_payload: Dict[str, Any] = {
            "round": r,
            "t_start": t_start,
            "t_end": t_end,
            "rsus": {rsu_id: sorted(list(vs)) for rsu_id, vs in rsu_membership.items()},
        }
        f_membership.write(json.dumps(membership_payload) + "\n")

        # 2) separate stats file (debugging / reporting)
        stats_payload: Dict[str, Any] = {
            "round": r,
            "t_start": t_start,
            "t_end": t_end,
            "vehicles_seen_count": len(round_unique_seen),
            "vehicles_connected_count": len(connected_vehicles),
            "uncovered_vehicle_time_s": round(round_uncovered_vehicle_time, 3),
            "rsu_total_connected_time_s": rsu_total_connected_time,
        }
        f_stats.write(json.dumps(stats_payload) + "\n")

    # Simulation loop
    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()
        t = traci.simulation.getTime()

        dt = 0.0 if prev_t is None else max(0.0, t - prev_t)
        prev_t = t

        r = int(t // ROUND_LENGTH)
        if current_round is None:
            current_round = r
            reset_round()
        elif r != current_round:
            flush_round(current_round)
            current_round = r
            reset_round()

        for veh_id in traci.vehicle.getIDList():
            round_unique_seen.add(veh_id)

            x_v, y_v = traci.vehicle.getPosition(veh_id)
            rsu_id = pick_closest_rsu(x_v, y_v)

            if rsu_id is None:
                round_uncovered_vehicle_time += dt
                continue

            if veh_id not in veh_rsu_time:
                veh_rsu_time[veh_id] = {}
            veh_rsu_time[veh_id][rsu_id] = veh_rsu_time[veh_id].get(rsu_id, 0.0) + dt

    if current_round is not None:
        flush_round(current_round)

    f_membership.close()
    f_stats.close()


if __name__ == "__main__":
    sumo_cmd = [SUMO_BINARY, "-c", SUMO_CFG, "--seed", "42"]
    traci.start(sumo_cmd)
    try:
        run()
    finally:
        traci.close()
