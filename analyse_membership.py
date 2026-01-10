import json
import csv
from pathlib import Path
from typing import Dict, Optional, Set, Any, List


IN_MEMBERSHIP = Path("round_membership.jsonl")
IN_STATS = Path("round_stats.jsonl")

OUT_RSU_STATS = Path("rsu_round_stats.csv")
OUT_ROUND_SUMMARY = Path("round_summary.csv")


def load_stats_by_round(path: Path) -> Dict[int, Dict[str, Any]]:
    by_round: Dict[int, Dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            by_round[int(rec["round"])] = rec
    return by_round


def invert_membership(rsus: Dict[str, List[str]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for rsu_id, vehs in rsus.items():
        for v in vehs:
            out[v] = rsu_id
    return out


def main():
    stats_by_round = load_stats_by_round(IN_STATS)
    prev_assign: Dict[str, Optional[str]] = {}

    with OUT_RSU_STATS.open("w", newline="", encoding="utf-8") as f_rsu, \
         OUT_ROUND_SUMMARY.open("w", newline="", encoding="utf-8") as f_round:

        rsu_writer = csv.writer(f_rsu)
        rsu_writer.writerow([
            "round", "t_start", "t_end",
            "rsu_id",
            "unique_vehicles",
            "total_connected_time_s",
            "handover_in", "handover_out",
        ])

        round_writer = csv.writer(f_round)
        round_writer.writerow([
            "round", "t_start", "t_end",
            "vehicles_seen_count",
            "vehicles_connected_count",
            "uncovered_vehicle_time_s",
        ])

        with IN_MEMBERSHIP.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                rec = json.loads(line)
                r = int(rec["round"])
                t_start = rec["t_start"]
                t_end = rec["t_end"]
                rsus: Dict[str, List[str]] = rec["rsus"]

                stats = stats_by_round.get(r, {})
                rsu_time = stats.get("rsu_total_connected_time_s", {})

                # Round summary (high value)
                round_writer.writerow([
                    r, t_start, t_end,
                    stats.get("vehicles_seen_count", ""),
                    stats.get("vehicles_connected_count", ""),
                    stats.get("uncovered_vehicle_time_s", ""),
                ])

                # Handover calc (medium value) from membership alone
                curr_assign = invert_membership(rsus)

                hand_in: Dict[str, int] = {rsu_id: 0 for rsu_id in rsus.keys()}
                hand_out: Dict[str, int] = {rsu_id: 0 for rsu_id in rsus.keys()}

                all_vehs: Set[str] = set(curr_assign.keys()) | set(prev_assign.keys())
                for v in all_vehs:
                    prev = prev_assign.get(v)
                    curr = curr_assign.get(v)
                    if prev is not None and curr is not None and prev != curr:
                        hand_out[prev] = hand_out.get(prev, 0) + 1
                        hand_in[curr] = hand_in.get(curr, 0) + 1

                # Per-RSU stats
                for rsu_id, vehs in rsus.items():
                    rsu_writer.writerow([
                        r, t_start, t_end,
                        rsu_id,
                        len(vehs),
                        rsu_time.get(rsu_id, ""),
                        hand_in.get(rsu_id, 0),
                        hand_out.get(rsu_id, 0),
                    ])

                # Update previous assignments (vehicles absent this round become None)
                prev_assign = {v: curr_assign.get(v) for v in all_vehs}

    print(f"Wrote {OUT_RSU_STATS}")
    print(f"Wrote {OUT_ROUND_SUMMARY}")


if __name__ == "__main__":
    main()
