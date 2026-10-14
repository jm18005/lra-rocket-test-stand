import ded_parser as dp
import pandas as pd
import sys


def read_csv(filepath):
    return pd.read_csv(filepath)


def add_materials_sections_to_ded(ded_data, materials_csv_path, j_factor=0.5):
    df = read_csv(materials_csv_path).fillna(0)

    rho_med = df["rho_kn_m3"].dropna().median()
    e_med = df["e_mpa"].dropna().median()
    fy_med = df["fy_mpa"].dropna().median()
    dp.add_material(ded_data, '8020net', e_med, 0.3, rho_med, fy_med)

    for row in df.itertuples(index=False):
        j = j_factor * (row.ix_m4 + row.iy_m4)

        dp.add_section(ded_data, row.part_number, row.a_m2, 
                       row.ix_m4, row.iy_m4, j)


def main():
    materials_csv_path = r"C:\Users\Josh\Documents\school\lra\8020_profiles.csv"
    ded_file = r"C:\Users\Josh\Downloads\3d_rocket_stand.ded"
    ded_data = dp.read_ded(ded_file)
    id_map = {
        "top_bar_L":          10,
        "top_bar_R":          9,
        "bottom_bar_L":       7,
        "bottom_bar_R":       8,
        "left_bar_top":       21,
        "left_bar_bottom":    25,
        "right_bar_top":      22,
        "right_bar_bottom":   24,
        "hydraulic_bar":      14,
        "out_of_page_bar":    18,
        "into_page_bar":      19,
        "oop_transverse_bar": 27, # has the load on it
        "itp_transverse_bar": 29
    }

    add_materials_sections_to_ded(ded_data, materials_csv_path)

    dp.write_ded(ded_data, r"C:\Users\Josh\Downloads\3d_rocket_stand2.ded")


if __name__ == "__main__":
    sys.exit(main())