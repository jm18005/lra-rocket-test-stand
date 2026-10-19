import ded_parser as dp
import pandas as pd
import sys
from pathlib import Path
import copy
from ai_example_code.stabileo_automation import StabileoSession, is_working_config

data_dir = Path(__file__).resolve().parent / "data"
materials_filepath = data_dir / "8020_profiles.csv"
materials_df = pd.read_csv(materials_filepath)

# Drop bad rows
required_cols = ["a_m2", "ix_m4", "iy_m4", "e_mpa", "rho_kn_m3", "fy_mpa"]
materials_df = materials_df.dropna(subset=required_cols)
materials_df = materials_df[(materials_df[required_cols] > 0).all(axis=1)]
materials_dicts = materials_df.to_dict("records")
materials_dicts.sort(key=lambda b: b["price_per_in_usd"], reverse=True)

def print_progress(current_iter: int, total_iters: int, bar_length: int = 30) -> None:
    fraction = current_iter / total_iters if total_iters > 0 else 1.0
    percent = fraction * 100.0
    filled_len = int(bar_length * fraction)
    bar = "=" * filled_len + "-" * (bar_length - filled_len)
    end_char = "\n" if current_iter >= total_iters else ""
    sys.stdout.write(f"\rProgress: [{bar}] {current_iter}/{total_iters} ({percent:5.1f}%)" + end_char)
    sys.stdout.flush()


def main():
    ded_filename0 = "3d_rocket_stand.ded"
    ded_filepath0 = data_dir / ded_filename0
    ded_data0 = dp.read_ded(str(ded_filepath0))

    # T = top
    # B = bottom
    # L = left
    # R = right
    # oop = Out of Page
    # itp = into page
    member_id_map = {
        "T_bar_L":             10,
        "T_bar_R":             9,
        "B_bar_L":             7,
        "B_bar_R":             8,
        "L_bar_T":             21,
        "L_bar_B":             25,
        "R_bar_T":             22,
        "R_bar_B":             24,
        "axial_hydraulic_bar": 14,
        "oop_bar":             18,
        "itp_bar":             19,
        "oop_transverse_bar":  27, # has the load on it
        "itp_transverse_bar":  29
    }
    members1 = [member_id_map["T_bar_L"], member_id_map["T_bar_R"], 
                member_id_map["B_bar_L"], member_id_map["B_bar_R"]]
    members2 = [member_id_map["L_bar_T"], member_id_map["L_bar_B"], 
            member_id_map["R_bar_T"], member_id_map["R_bar_B"]]
    members3 = [member_id_map["axial_hydraulic_bar"]]
    members4 = [member_id_map["oop_bar"], member_id_map["itp_bar"],
            member_id_map["oop_transverse_bar"], member_id_map["itp_transverse_bar"]]
    
    n_iters = len(materials_dicts)**4
    print(f"Running {n_iters} Iterations")
    best_stand_cost = 246 # 245.10
    best_config = None
    with StabileoSession(headless=True) as session:
        for outer_iter, bar1 in enumerate(materials_dicts):
            ded_data1 = copy.deepcopy(ded_data0)
            total_cost1 = dp.calc_bar_cost(ded_data1, bar1, members1)
            if total_cost1 > best_stand_cost:
                continue
            dp.assign_from_8020_profiles(ded_data1, bar1, members1)
            
            for bar2 in materials_dicts:
                ded_data2 = copy.deepcopy(ded_data1)
                total_cost2 = copy.copy(total_cost1)
                total_cost2 += dp.calc_bar_cost(ded_data2, bar2, members2)
                if total_cost2 > best_stand_cost:
                    continue
                dp.assign_from_8020_profiles(ded_data2, bar2, members2)

                for bar3 in materials_dicts:
                    ded_data3 = copy.deepcopy(ded_data2)
                    total_cost3 = copy.copy(total_cost2)
                    total_cost3 += dp.calc_bar_cost(ded_data3, bar3, members3)
                    if total_cost3 > best_stand_cost:
                            continue
                    dp.assign_from_8020_profiles(ded_data3, bar3, members3)

                    for bar4 in materials_dicts:
                        ded_data4 = copy.deepcopy(ded_data3)
                        total_cost4 = copy.copy(total_cost3)
                        total_cost4 += dp.calc_bar_cost(ded_data4, bar4, members4)
                        if total_cost4 > best_stand_cost:
                            continue
                        dp.assign_from_8020_profiles(ded_data4, bar4, members4)
                        
                        dp.write_ded(ded_data4, "test.ded")
                        analysis_results = session.solve(
                            "test.ded",
                            include_buckling=True,
                            include_pdelta=True,
                        )
                        member_to_bar = {
                            **{m: bar1 for m in members1},
                            **{m: bar2 for m in members2},
                            **{m: bar3 for m in members3},
                            **{m: bar4 for m in members4},
                        }
                        working_config = is_working_config(analysis_results, member_to_bar)
                        if working_config:
                            best_stand_cost = total_cost4
                            best_config = (bar1["part_number"], bar2["part_number"], bar3["part_number"], bar4["part_number"], ded_data4)
                            print(best_stand_cost)
                        

            print_progress(outer_iter+1, len(materials_dicts))
        print(best_config)

if __name__ == "__main__":
    sys.exit(main())