import json
import random
from pathlib import Path
from typing import Dict, List, Set, Any


MEMBERSHIP_JSONL = Path("round_membership.jsonl")

DATASET_SIZE = 60000      # e.g., MNIST train size (change for CIFAR: 50000)
BUNDLE_SIZE = 200         # indices per vehicle (tune)
SEED = 42

OUT_VEH_BUNDLES = Path("vehicle_bundles.json")
OUT_PER_ROUND = Path("rsu_round_indices.jsonl")
OUT_CUMULATIVE = Path("rsu_round_indices_cumulative.jsonl")


def load_rounds(path: Path) -> List[Dict[str, Any]]:
    rounds = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rounds.append(json.loads(line))
    return rounds


def collect_all_vehicles(rounds: List[Dict[str, Any]]) -> List[str]:
    vehs: Set[str] = set()
    for r in rounds:
        for veh_list in r["rsus"].values():
            vehs.update(veh_list)
    return sorted(vehs)


def assign_disjoint_bundles(veh_ids: List[str], dataset_size: int, bundle_size: int, seed: int) -> Dict[str, List[int]]:
    """
    Disjoint bundles = each index belongs to at most one vehicle.
    Clean baseline: avoids overlap and makes accounting easy.
    """
    needed = len(veh_ids) * bundle_size
    if needed > dataset_size:
        raise ValueError(
            f"Not enough indices for disjoint bundles: need {needed}, have {dataset_size}. "
            f"Reduce BUNDLE_SIZE or increase DATASET_SIZE or allow overlap."
        )

    rng = random.Random(seed)
    indices = list(range(dataset_size))
    rng.shuffle(indices)

    bundles: Dict[str, List[int]] = {}
    cursor = 0
    for v in veh_ids:
        bundles[v] = indices[cursor: cursor + bundle_size]
        cursor += bundle_size
    return bundles


def main():
    rounds = load_rounds(MEMBERSHIP_JSONL)
    veh_ids = collect_all_vehicles(rounds)
    print(f"Rounds: {len(rounds)} | Unique vehicles: {len(veh_ids)}")

    vehicle_bundles = assign_disjoint_bundles(veh_ids, DATASET_SIZE, BUNDLE_SIZE, SEED)
    OUT_VEH_BUNDLES.write_text(json.dumps(vehicle_bundles), encoding="utf-8")
    print(f"Wrote {OUT_VEH_BUNDLES}")

    cumulative: Dict[str, Set[int]] = {}

    with OUT_PER_ROUND.open("w", encoding="utf-8") as f_round, OUT_CUMULATIVE.open("w", encoding="utf-8") as f_cum:
        for rec in rounds:
            r = rec["round"]
            rsus = rec["rsus"]

            round_out: Dict[str, List[int]] = {}
            cum_out: Dict[str, List[int]] = {}

            for rsu_id, veh_list in rsus.items():
                # per-round union
                u: Set[int] = set()
                for v in veh_list:
                    u.update(vehicle_bundles[v])
                round_out[rsu_id] = sorted(u)

                # cumulative union (recommended baseline)
                if rsu_id not in cumulative:
                    cumulative[rsu_id] = set()
                cumulative[rsu_id].update(u)
                cum_out[rsu_id] = sorted(cumulative[rsu_id])

            f_round.write(json.dumps({"round": r, "rsus": round_out}) + "\n")
            f_cum.write(json.dumps({"round": r, "rsus": cum_out}) + "\n")

    print(f"Wrote {OUT_PER_ROUND}")
    print(f"Wrote {OUT_CUMULATIVE}")


if __name__ == "__main__":
    main()
