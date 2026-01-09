import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt


FCD_FILE = Path("/Users/niki/Sumo/2026-01-09-13-02-29/fcd.xml")  # change to your filename

# Heatmap resolution: increase for finer grid
NUM_BINS_X = 100
NUM_BINS_Y = 100

# Optional: time filtering (e.g. only from t_start to t_end)
T_START = None  # e.g. 0.0
T_END = None    # e.g. 3600.0

# How many RSUs to pick and minimal distance between them (in SUMO coords)
NUM_RSUS = 4
MIN_RSU_DISTANCE = 200.0  # set to 0.0 if you don't care about spacing


def parse_fcd_positions(fcd_path: Path):
    xs = []
    ys = []

    tree = ET.parse(fcd_path)
    root = tree.getroot()

    for timestep in root.findall("timestep"):
        t = float(timestep.get("time", 0.0))

        if T_START is not None and t < T_START:
            continue
        if T_END is not None and t > T_END:
            continue

        for veh in timestep.findall("vehicle"):
            x = float(veh.get("x"))
            y = float(veh.get("y"))
            xs.append(x)
            ys.append(y)

    return np.array(xs), np.array(ys)


def build_heatmap(xs, ys, num_bins_x=100, num_bins_y=100):
    # Determine bounds from data
    x_min, x_max = xs.min(), xs.max()
    y_min, y_max = ys.min(), ys.max()

    # 2D histogram: counts per grid cell
    heatmap, x_edges, y_edges = np.histogram2d(
        xs, ys,
        bins=[num_bins_x, num_bins_y],
        range=[[x_min, x_max], [y_min, y_max]],
    )

    return heatmap, x_edges, y_edges


def select_rsu_positions(heatmap, x_edges, y_edges,
                         k=4, min_dist=0.0):
    """
    Pick up to k RSU positions at the centers of the hottest cells
    in the heatmap, enforcing a minimum distance between RSUs.
    """
    rsu_positions = []

    # Flatten heatmap, sort indices by descending count
    flat_indices = np.argsort(heatmap.ravel())[::-1]
    H, W = heatmap.shape  # H = num_bins_x, W = num_bins_y

    for flat_idx in flat_indices:
        if len(rsu_positions) >= k:
            break

        i = flat_idx // W  # x-bin index
        j = flat_idx % W   # y-bin index

        # Skip empty cells
        if heatmap[i, j] <= 0:
            continue

        # Center of this cell
        x_center = 0.5 * (x_edges[i] + x_edges[i + 1])
        y_center = 0.5 * (y_edges[j] + y_edges[j + 1])
        candidate = (x_center, y_center)

        # Enforce minimum spacing between RSUs
        too_close = False
        for (x0, y0) in rsu_positions:
            dist = np.hypot(x_center - x0, y_center - y0)
            if dist < min_dist:
                too_close = True
                break

        if too_close:
            continue

        rsu_positions.append(candidate)

    return rsu_positions


def plot_heatmap(heatmap, x_edges, y_edges,
                 rsu_positions=None,
                 out_png="fcd_heatmap.png"):
    # Extent = [x_min, x_max, y_min, y_max]
    extent = [x_edges[0], x_edges[-1], y_edges[0], y_edges[-1]]

    plt.figure(figsize=(8, 6))
    plt.imshow(
        heatmap.T,           # transpose so X/Y align as expected
        origin="lower",
        extent=extent,
        aspect="equal",
    )
    plt.colorbar(label="vehicle count")
    plt.xlabel("x (SUMO coords)")
    plt.ylabel("y (SUMO coords)")
    plt.title("Vehicle density heatmap")

    # Optionally overlay RSU positions as markers
    if rsu_positions:
        xs = [p[0] for p in rsu_positions]
        ys = [p[1] for p in rsu_positions]
        plt.scatter(xs, ys, marker="x", s=80)
        for idx, (x, y) in enumerate(rsu_positions):
            plt.text(x, y, f"RSU{idx}", color="white",
                     ha="left", va="bottom")

    plt.tight_layout()
    plt.savefig(out_png, dpi=200)
    print(f"Saved heatmap to {out_png}")


def main():
    print(f"Parsing {FCD_FILE} ...")
    xs, ys = parse_fcd_positions(FCD_FILE)
    print(f"Collected {len(xs)} positions")

    heatmap, x_edges, y_edges = build_heatmap(xs, ys,
                                              num_bins_x=NUM_BINS_X,
                                              num_bins_y=NUM_BINS_Y)

    # --- NEW PART: automatically select RSU positions ---
    rsu_positions = select_rsu_positions(
        heatmap, x_edges, y_edges,
        k=NUM_RSUS,
        min_dist=MIN_RSU_DISTANCE,
    )

    print("Suggested RSU positions (SUMO coords):")
    for idx, (x, y) in enumerate(rsu_positions):
        print(f"  rsu_{idx}: x={x:.2f}, y={y:.2f}")

    print("\nCopy-paste into your TraCI script, e.g.:")
    print("RSUS = {")
    for idx, (x, y) in enumerate(rsu_positions):
        print(f'    "rsu_{idx}": {{"x": {x:.2f}, "y": {y:.2f}, "radius": 150.0}},')
    print("}")

    # Plot heatmap with RSU markers overlaid
    plot_heatmap(heatmap, x_edges, y_edges,
                 rsu_positions=rsu_positions,
                 out_png="fcd_heatmap_with_rsus.png")


if __name__ == "__main__":
    main()
