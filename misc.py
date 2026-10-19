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