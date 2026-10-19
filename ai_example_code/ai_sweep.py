from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd
import ded_parser as dp
from ai_example_code.stabileo_automation import StabileoSession, is_working_config

DATA_DIR = ROOT_DIR / "data"
MATERIALS_FILEPATH = DATA_DIR / "8020_profiles.csv"
BASE_DED_FILEPATH = DATA_DIR / "3d_rocket_stand.ded"
TEST_FILEPATH = str(ROOT_DIR / "test.ded")
OPTIMAL_FILEPATH = str(ROOT_DIR / "optimal_3d_rocket_stand.ded")


def calc_group_cost_usd(ded_data: dict[str, Any], bar: dict[str, Any], member_ids: list[int]) -> float:
    cost_usd = 0.0
    for member_id in member_ids:
        length_in = dp.calc_member_len(ded_data, member_id, unit_mult=dp.M2IN)
        cost_usd += float(bar["price_per_in_usd"]) * length_in
    return cost_usd


def calc_total_stand_cost_usd(
    ded_data: dict[str, Any],
    profiles: list[dict[str, Any]],
    cfg: list[int],
    member_groups: list[list[int]],
) -> float:
    total_cost_usd = 0.0
    for group_idx, profile_idx in enumerate(cfg):
        bar = profiles[profile_idx]
        members = member_groups[group_idx]
        total_cost_usd += calc_group_cost_usd(ded_data, bar, members)
    return total_cost_usd


def evaluate_configuration(
    session: StabileoSession,
    base_ded: dict[str, Any],
    profiles: list[dict[str, Any]],
    cfg: list[int],
    member_groups: list[list[int]],
    test_filepath: str = TEST_FILEPATH,
) -> bool:
    ded_copy = copy.deepcopy(base_ded)
    member_to_bar: dict[int, dict[str, Any]] = {}

    for group_idx, profile_idx in enumerate(cfg):
        bar = profiles[profile_idx]
        members = member_groups[group_idx]
        dp.assign_from_8020_profiles(ded_copy, bar, members)
        for mid in members:
            member_to_bar[mid] = bar

    dp.write_ded(ded_copy, test_filepath)
    results = session.solve(
        test_filepath,
        include_buckling=True,
        include_pdelta=True,
    )
    return is_working_config(results, member_to_bar)


def print_progress(current: int, total: int, bar_length: int = 30, label: str = "") -> None:
    fraction = current / total if total > 0 else 1.0
    percent = fraction * 100.0
    filled = int(bar_length * fraction)
    bar = "=" * filled + "-" * (bar_length - filled)
    end_char = "\n" if current >= total else ""
    sys.stdout.write(f"\r[{bar}] {current}/{total} ({percent:5.1f}%) {label}" + end_char)
    sys.stdout.flush()


def run_coordinate_descent_sweep() -> None:
    # 1. Load profiles and filter purely invalid rows
    materials_df = pd.read_csv(MATERIALS_FILEPATH)
    required_cols = ["a_m2", "ix_m4", "iy_m4", "e_mpa", "rho_kn_m3", "fy_mpa"]
    materials_df = materials_df.dropna(subset=required_cols)
    materials_df = materials_df[(materials_df[required_cols] > 0).all(axis=1)]
    materials_df = materials_df.sort_values("price_per_in_usd")
    profiles = materials_df.to_dict("records")
    n_profiles = len(profiles)

    # 2. Load base model and map members
    ded_data0 = dp.read_ded(str(BASE_DED_FILEPATH))
    ded_data0["snapshot"]["sections"] = [
        s for s in ded_data0["snapshot"]["sections"] if s[1].get("a", 0) > 0
    ]

    member_id_map = {
        "T_bar_L": 10,
        "T_bar_R": 9,
        "B_bar_L": 7,
        "B_bar_R": 8,
        "L_bar_T": 21,
        "L_bar_B": 25,
        "R_bar_T": 22,
        "R_bar_B": 24,
        "axial_hydraulic_bar": 14,
        "oop_bar": 18,
        "itp_bar": 19,
        "oop_transverse_bar": 27,
        "itp_transverse_bar": 29,
    }

    group_names = ["top_bottom_frame", "columns", "hydraulic_bar", "transverse_bars"]
    member_groups = [
        [member_id_map["T_bar_L"], member_id_map["T_bar_R"], member_id_map["B_bar_L"], member_id_map["B_bar_R"]],
        [member_id_map["L_bar_T"], member_id_map["L_bar_B"], member_id_map["R_bar_T"], member_id_map["R_bar_B"]],
        [member_id_map["axial_hydraulic_bar"]],
        [member_id_map["oop_bar"], member_id_map["itp_bar"], member_id_map["oop_transverse_bar"], member_id_map["itp_transverse_bar"]],
    ]

    print(f"Loaded {n_profiles} candidate 8020 profiles.")
    print("Initializing browser session...")

    with StabileoSession(headless=True) as session:
        # Start at the strongest profile (highest capacity) as baseline
        current_cfg = [n_profiles - 1, n_profiles - 1, n_profiles - 1, n_profiles - 1]
        print(f"Verifying sturdy baseline ({profiles[-1]['part_number']})...")
        baseline_valid = evaluate_configuration(session, ded_data0, profiles, current_cfg, member_groups)
        if not baseline_valid:
            print("Warning: Sturdy baseline did not pass checks; running search regardless.")

        best_cost_usd = calc_total_stand_cost_usd(ded_data0, profiles, current_cfg, member_groups)
        print(f"Baseline stand cost: ${best_cost_usd:.2f}")

        # Sweep order: columns (78% of length), top/bottom, hydraulic, transverse
        sweep_order = [1, 0, 2, 3]
        total_evals = 0

        for cycle in range(2):
            print(f"\n--- Optimization Cycle {cycle + 1} ---")
            changed = False

            for group_idx in sweep_order:
                name = group_names[group_idx]
                curr_pidx = current_cfg[group_idx]
                print(f"Sweeping {name} (current: {profiles[curr_pidx]['part_number']})...")

                # Test from cheapest profile index 0 up to current profile
                for test_pidx in range(curr_pidx):
                    total_evals += 1
                    test_cfg = list(current_cfg)
                    test_cfg[group_idx] = test_pidx

                    # Check if total cost is lower than current best
                    cand_cost = calc_total_stand_cost_usd(ded_data0, profiles, test_cfg, member_groups)
                    if cand_cost >= best_cost_usd:
                        continue

                    print_progress(test_pidx + 1, curr_pidx, label=f"testing {profiles[test_pidx]['part_number']}")

                    is_valid = evaluate_configuration(session, ded_data0, profiles, test_cfg, member_groups)
                    if is_valid:
                        current_cfg[group_idx] = test_pidx
                        best_cost_usd = cand_cost
                        changed = True
                        print(f"\n  Found cheaper working profile for {name}: {profiles[test_pidx]['part_number']} (${best_cost_usd:.2f})")
                        break
                print_progress(curr_pidx, curr_pidx, label="done\n")

            if not changed:
                print("Converged: no group profile changed in this cycle.")
                break

        print("\n================== Optimization Result ==================")
        print(f"Total model evaluations: {total_evals}")
        print(f"Optimal Stand Cost: ${best_cost_usd:.2f}")
        for g_idx, p_idx in enumerate(current_cfg):
            bar = profiles[p_idx]
            g_cost = calc_group_cost_usd(ded_data0, bar, member_groups[g_idx])
            print(f"  {group_names[g_idx]:<20}: {bar['part_number']} (${g_cost:.2f})")

        # Save optimal model
        best_ded = copy.deepcopy(ded_data0)
        for g_idx, p_idx in enumerate(current_cfg):
            dp.assign_from_8020_profiles(best_ded, profiles[p_idx], member_groups[g_idx])
        dp.write_ded(best_ded, OPTIMAL_FILEPATH)
        print(f"Saved optimal model to {OPTIMAL_FILEPATH}")


def main() -> None:
    run_coordinate_descent_sweep()


if __name__ == "__main__":
    main()

